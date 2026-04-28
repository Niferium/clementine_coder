import signal
import sys

def signal_handler(sig, frame):
    print('Hello World')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

try:
    while True:
        pass
except KeyboardInterrupt:
    print('Hello World')