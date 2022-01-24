from train_lib.clients import Consumer, PHTClient
from train_lib.clients.rabbitmq import LOG_FORMAT
import json
from dotenv import load_dotenv, find_dotenv
import os
import logging
from builder.TrainBuilder import TrainBuilder, BuildStatus
from loguru import logger

LOGGER = logging.getLogger(__name__)


class TBConsumer(Consumer):

    def __init__(self, amqp_url: str, queue: str = "", public_key_path: str = None, routing_key: str = None):
        super().__init__(amqp_url, queue, routing_key=routing_key)
        api_url = os.getenv("UI_TRAIN_API")
        if api_url[-1] != "/":
            api_url += "/"

        vault_url = os.getenv("VAULT_URL")
        if vault_url[-1] != "/":
            vault_url = vault_url + "/"

        self.pht_client = PHTClient(ampq_url=amqp_url, api_url=api_url,
                                    vault_url=vault_url, vault_token=os.getenv("VAULT_TOKEN"))

        self.builder = TrainBuilder(self.pht_client)

        if public_key_path:
            with open(public_key_path, "r") as public_key_file:
                self.pk = public_key_file.read()

        # Set auto reconnect to tr
        self.auto_reconnect = True
        # Configure routing key
        self.ROUTING_KEY = "tb"

    def on_message(self, _unused_channel, basic_deliver, properties, body):
        try:
            message = json.loads(body)
            # print(json.dumps(message, indent=2))
        except:
            self.pht_client.publish_message_rabbit_mq(
                {"type": BuildStatus.FAILED.value, "data": {"message": "Malformed JSON"}},
                routing_key="ui.tb.event")
            super().on_message(_unused_channel, basic_deliver, properties, body)
            return
        logger.info(f"Received message: \n {message}")
        action, data, meta_data = self._process_queue_message(message)

        if action in ["trainBuildStart", "trainBuild"]:
            logger.info("Received build command")
            build_started_message = {
                "type": BuildStatus.STARTED.value,
                "data": {
                    "trainId": data["trainId"],
                }
            }
            self.pht_client.publish_message_rabbit_mq(
                build_started_message,
                routing_key="ui.tb.event"
            )
            code, build_message = self.builder.build_train(data, meta_data)
            if code == 0:
                # Post updates for tr to get the route from vault
                self.post_message_for_train_router(data)
            else:
                self.builder.set_redis_status(data["trainId"], BuildStatus.FAILED)

            response = self._make_response(message, code, build_message)

        elif action == "trainBuildStop":

            response = {
                "type": BuildStatus.STOPPED.value,
                "data": {
                    "trainId": data["trainId"]
                }
            }
            # todo actually stop the build if possible
            logger.info(f"Stopping train build for train:  {data['trainId']}")
            self.builder.set_redis_status(data["trainId"], BuildStatus.STOPPED)

        elif action == "trainBuildStatus":
            response = self.builder.get_train_status(data["trainId"])
        else:
            logger.warning(f"Received unrecognized action type - {action}")
            response = self._make_response(message, 1, f"Unrecognized action type: {action}")

        # Notify the UI that the train has been built
        self.pht_client.publish_message_rabbit_mq(response, routing_key="ui.tb.event")
        super().on_message(_unused_channel, basic_deliver, properties, body)

    def post_message_for_train_router(self, data: dict):
        """
        Notifies the train router via RabbitMQ that the train has been built and the route is stored in vault

        :param data: build data for the train
        :return:
        """

        message = {
            "type": "trainBuilt",
            "data": {
                "trainId": data["trainId"]
            }
        }

        self.pht_client.publish_message_rabbit_mq(message, routing_key="tr")

    @staticmethod
    def _process_queue_message(message):
        data = message["data"]
        meta_data = message["metadata"]
        action = message["type"]
        return action, data, meta_data

    @staticmethod
    def _make_response(message, code, build_message):
        if code == 0:
            message["type"] = BuildStatus.FINISHED.value
        else:
            message["type"] = BuildStatus.FAILED.value
        message["data"]["buildMessage"] = build_message

        return message


def main():
    load_dotenv(find_dotenv())
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    tb_consumer = TBConsumer(os.getenv("AMPQ_URL"), "", routing_key="tb")
    # os.getenv("UI_TRAIN_API")
    tb_consumer.run()


if __name__ == '__main__':
    main()