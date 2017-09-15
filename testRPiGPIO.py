#!/usr/bin/python
BOARD = "board"
BCM = "bcm"
OUT = "out"
IN = "in"


def output(pin, value):
    print(pin, ":", value)


def setmode(mode):
    print(mode)


def setup(pin, value):
    print(pin, ":", value)


def cleanup():
    print("clean-up")


def input(pin):
    print(pin, ":")

    # End


def gpio_function(pin):
    print(pin, ":")
    return OUT


def setwarnings(flag):
    print('False')
