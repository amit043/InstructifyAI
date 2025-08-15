from celery import Celery

app = Celery("worker", broker="redis://redis:6379/0")


@app.task
def noop() -> None:
    return None


if __name__ == "__main__":
    app.worker_main()
