

class Stopwatch:
    def __init__(self):
        self.start_time = None
        self.end_time = None

    def start(self):
        import time
        self.start_time = time.time()

    def stop(self):
        import time
        self.end_time = time.time()

    def elapsed_time(self):
        if self.start_time is None or self.end_time is None:
            raise ValueError("Stopwatch has not been started and stopped properly.")
        return self.end_time - self.start_time