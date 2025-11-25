FROM python:3

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir data

COPY config.json ./config.json
COPY auth.py ./
COPY main.py ./

CMD [ "python", "-u", "./main.py" ]
