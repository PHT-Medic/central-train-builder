FROM python:3.8-slim
COPY ./src /home/src
COPY .env /home
COPY rsa.public /home/rsa.public
COPY requirements.txt /home/requirements.txt
COPY TrainBuilderService.py /home/TrainBuilderService.py

RUN pip install -r /home/requirements.txt

CMD ["python", "-u", "/home/TrainBuilderService.py"]
