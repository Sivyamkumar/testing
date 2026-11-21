FROM python:3.10-slim-bullseye

WORKDIR /app
COPY ./requirements.txt /app
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt
COPY . /app

EXPOSE 3000

CMD ["gunicorn", "-b", "0.0.0.0:3000", "--timeout", "300", "app:app"]
