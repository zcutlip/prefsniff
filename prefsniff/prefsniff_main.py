import sys
from .prefsniff import main as prefsniff_main


def main():
    try:
        prefsniff_main(sys.argv[1:])
    except KeyboardInterrupt:
        print("Iterrupted. Terminating.")
        exit(1)
