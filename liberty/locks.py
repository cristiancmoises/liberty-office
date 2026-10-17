"""One owner of a data directory, acquired before opening/migrating its database."""
import fcntl
from pathlib import Path
class VolumeLock:
    def __init__(self,directory):self.directory=Path(directory);self.file=None
    def acquire(self):
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.file=(self.directory/'server.lock').open('a')
        try:fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close();self.file=None
            raise RuntimeError('Pare a outra instância antes de usar este volume.')
        return self
    def release(self):
        if self.file:
            fcntl.flock(self.file,fcntl.LOCK_UN);self.file.close();self.file=None
    def __enter__(self):return self.acquire()
    def __exit__(self,*exc):self.release()
