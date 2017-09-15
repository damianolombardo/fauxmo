"""
GPIORPiPlugin.py :: Fauxmo plugin for simple RPi.GPIO.
"""
try:
    import RPi.GPIO as GPIO
except ImportError:
    import testRPiGPIO as GPIO

    print('Using testRPiGPIO')
from functools import partialmethod  # type: ignore # not yet in typeshed
from fauxmo.plugins import FauxmoPlugin
from time import sleep
import sys

DEBUG = True


def dbg(msg):
    global DEBUG
    if DEBUG:
        print(msg)
        sys.stdout.flush()


def gpio_handler(pins, state=None):
    if type(pins) is not list:
        pins = [pins]
    if state == 'input':
        for p in pins:
            GPIO.input(p, state)
    else:
        for p in pins:
            GPIO.output(p, state)


class GPIORPiPlugin(FauxmoPlugin):
    """Fauxmo Plugin for running commands on the local machine."""

    def __init__(self, *, name: str, port: int, on_cmd: int, off_cmd: int, pin: int or list, mode: str,
                 switching_type: str) -> None:
        """Initialize a GPIORPiPlugin instance.
        Args:
            name: Name for this Fauxmo device
            port: Port on which to run a specific GPIORPiPlugin instance
            on_cmd: Command to be called when turning device on
            off_cmd: Command to be called when turning device off
            pin: GPIO pin number
            mode: GPIO mode eg BCM, BOARD
            switching_type: What kind of output to send, oneshot, toggle
       """
        self.on_cmd = on_cmd
        self.off_cmd = off_cmd
        self.pin = pin
        self.mode = mode
        self.switching_type = switching_type
        if mode == 'BCM':
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.pin, GPIO.OUT)
            self.internal_state = GPIO.input(self.pin)
        elif mode == 'BOARD':
            GPIO.setmode(GPIO.BOARD)
            GPIO.setup(self.pin, GPIO.OUT)
            self.internal_state = GPIO.input(self.pin)
        elif mode == 'LEECH':
            if type(self.pin) is list:
                for p in self.pin:
                    if GPIO.gpio_function(p) != GPIO.OUT:
                        raise Exception('Pin %i has not been defined as standalone switch' % p)
            elif type(self.pin) is int:
                dbg('Leech Mode Set for pin %i' % self.pin)

        if self.switching_type == 'oneshot':
            self.func = self.oneshot
        else:
            self.func = self.toggle

        super().__init__(name=name, port=port)

    def oneshot(self, cmd: str) -> bool:
        """Partialmethod to run command.
        Args:
            cmd: Will be one of `"on_cmd"` or `"off_cmd"`, which `getattr` will
                 use to get the instance attribute.
        """
        state = getattr(self, cmd)
        gpio_handler(self.pin, state)
        sleep(2)
        gpio_handler(self.pin, 1 - state)
        self.internal_state = state
        return True

    def toggle(self, cmd: str) -> bool:
        """Partialmethod to run command.
        Args:
            cmd: Will be one of `"on_cmd"` or `"off_cmd"`, which `getattr` will
                 use to get the instance attribute.
        """
        state = getattr(self, cmd)
        gpio_handler(self.pin, state)
        self.internal_state = GPIO.input(self.pin)
        return True

    def run_cmd(self, cmd: str):
        return self.func(cmd)

    on = partialmethod(run_cmd, "on_cmd")
    off = partialmethod(run_cmd, "off_cmd")


if __name__ == "__main__":
    print('Create switch')
    test1 = GPIORPiPlugin(name="test switch", port=12345, on_cmd=1, off_cmd=0, pin=14, mode='BCM',
                          switching_type='toggle')
    test2 = GPIORPiPlugin(name="test switch", port=12345, on_cmd=1, off_cmd=0, pin=15, mode='BCM',
                          switching_type='toggle')
    test3 = GPIORPiPlugin(name="test switch", port=12345, on_cmd=1, off_cmd=0, pin=18, mode='BCM',
                          switching_type='toggle')
    test4 = GPIORPiPlugin(name="test switch", port=12345, on_cmd=1, off_cmd=0, pin=[14, 15, 18], mode='LEECH',
                          switching_type='toggle')
    print('test on')
    test1.on()
    print('test off')
    test1.off()
    test4.on()
