#!/usr/bin/env python

"""
The MIT License (MIT)
Copyright (c) 2015 Maker Musings
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

# For a complete discussion, see http://www.makermusings.com

import email.utils
# import requests
import select
import socket
import struct
import sys
import time
# import urllib
import uuid

try:
    import RPi.GPIO as GPIO
except ImportError:
    import testRPiGPIO as GPIO

# This XML is the minimum needed to define one of our virtual switches
# to the Amazon Echo

SETUP_XML = """<?xml version="1.0"?>
<root>
  <device>
    <deviceType>urn:MakerMusings:device:controllee:1</deviceType>
    <friendlyName>%(device_name)s</friendlyName>
    <manufacturer>Belkin International Inc.</manufacturer>
    <modelName>Emulated Socket</modelName>
    <modelNumber>3.1415</modelNumber>
    <UDN>uuid:Socket-1_0-%(device_serial)s</UDN>
  </device>
</root>
"""

DEBUG = False


def dbg(msg):
    global DEBUG
    if DEBUG:
        print(msg)
        sys.stdout.flush()


# A simple utility class to wait for incoming data to be
# ready on a socket.

class Poller:
    def __init__(self):
        if 'poll' in dir(select):
            self.use_poll = True
            self.poller = select.poll()
        else:
            self.use_poll = False
        self.targets = {}

    def add(self, target, fileno=None):
        if not fileno:
            fileno = target.fileno()
        if self.use_poll:
            self.poller.register(fileno, select.POLLIN)
        self.targets[fileno] = target

    def remove(self, target, fileno=None):
        if not fileno:
            fileno = target.fileno()
        if self.use_poll:
            self.poller.unregister(fileno)
        del (self.targets[fileno])

    def poll(self, timeout=0):
        if self.use_poll:
            ready = self.poller.poll(timeout)
        else:
            ready = []
            if len(self.targets) > 0:
                (rlist, wlist, xlist) = select.select(self.targets.keys(), [], [], timeout)
                ready = [(x, None) for x in rlist]
        for one_ready in ready:
            target = self.targets.get(one_ready[0], None)
            if target:
                target.do_read(one_ready[0])


# Base class for a generic UPnP device. This is far from complete
# but it supports either specified or automatic IP address and port
# selection.

class UPnPDevice(object):
    this_host_ip = None

    @staticmethod
    def local_ip_address():
        if not UPnPDevice.this_host_ip:
            temp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                temp_socket.connect(('8.8.8.8', 53))
                UPnPDevice.this_host_ip = temp_socket.getsockname()[0]
            except:
                UPnPDevice.this_host_ip = '127.0.0.1'
            del temp_socket
            dbg("got local address of %s" % UPnPDevice.this_host_ip)
        return UPnPDevice.this_host_ip

    def __init__(self, listener, poller, port, root_url, server_version, persistent_uuid, other_headers=None,
                 ip_address=None):
        self.listener = listener
        self.poller = poller
        self.port = port
        self.root_url = root_url
        self.server_version = server_version
        self.persistent_uuid = persistent_uuid
        self.uuid = uuid.uuid4()
        self.other_headers = other_headers

        if ip_address:
            self.ip_address = ip_address
        else:
            self.ip_address = UPnPDevice.local_ip_address()

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind((self.ip_address, self.port))
        self.socket.listen(5)
        if self.port == 0:
            self.port = self.socket.getsockname()[1]
        self.poller.add(self)
        self.client_sockets = {}
        self.listener.add_device(self)

    def fileno(self):
        return self.socket.fileno()

    def do_read(self, fileno):
        if fileno == self.socket.fileno():
            (client_socket, client_address) = self.socket.accept()
            self.poller.add(self, client_socket.fileno())
            self.client_sockets[client_socket.fileno()] = client_socket
        else:
            data, sender = self.client_sockets[fileno].recvfrom(4096)
            if not data:
                self.poller.remove(self, fileno)
                del (self.client_sockets[fileno])
            else:
                self.handle_request(data, sender, self.client_sockets[fileno])

    def handle_request(self, data, sender, socket):
        pass

    def get_name(self):
        return "unknown"

    def respond_to_search(self, destination, search_target):
        dbg("Responding to search for %s" % self.get_name())
        date_str = email.utils.formatdate(timeval=None, localtime=False, usegmt=True)
        location_url = self.root_url % {'ip_address': self.ip_address, 'port': self.port}
        message = ("HTTP/1.1 200 OK\r\n"
                   "CACHE-CONTROL: max-age=86400\r\n"
                   "DATE: %s\r\n"
                   "EXT:\r\n"
                   "LOCATION: %s\r\n"
                   "OPT: \"http://schemas.upnp.org/upnp/1/0/\"; ns=01\r\n"
                   "01-NLS: %s\r\n"
                   "SERVER: %s\r\n"
                   "ST: %s\r\n"
                   "USN: uuid:%s::%s\r\n" % (
                       date_str, location_url, self.uuid, self.server_version, search_target, self.persistent_uuid,
                       search_target))
        if self.other_headers:
            for header in self.other_headers:
                message += "%s\r\n" % header
        message += "\r\n"
        temp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        temp_socket.sendto(message, destination)


# This subclass does the bulk of the work to mimic a WeMo switch on the network.

class Fauxmo(UPnPDevice):
    @staticmethod
    def make_uuid(name):
        return ''.join(["%x" % sum([ord(c) for c in name])] + ["%x" % ord(c) for c in "%sfauxmo!" % name])[:14]

    def __init__(self, name, listener, poller, ip_address, port, action_handler=None):
        self.serial = self.make_uuid(name)
        self.name = name
        self.ip_address = ip_address
        persistent_uuid = "Socket-1_0-" + self.serial
        other_headers = ['X-User-Agent: redsonic']
        UPnPDevice.__init__(self, listener, poller, port, "http://%(ip_address)s:%(port)s/setup.xml",
                            "Unspecified, UPnP/1.0, Unspecified", persistent_uuid, other_headers=other_headers,
                            ip_address=ip_address)
        if action_handler:
            self.action_handler = action_handler
        else:
            self.action_handler = self
        dbg("FauxMo device '%s' ready on %s:%s" % (self.name, self.ip_address, self.port))

    def get_name(self):
        return self.name

    def handle_request(self, data, sender, socket):
        if data.find('GET /setup.xml HTTP/1.1') == 0:
            dbg("Responding to setup.xml for %s" % self.name)
            xml = SETUP_XML % {'device_name': self.name, 'device_serial': self.serial}
            date_str = email.utils.formatdate(timeval=None, localtime=False, usegmt=True)
            message = ("HTTP/1.1 200 OK\r\n"
                       "CONTENT-LENGTH: %d\r\n"
                       "CONTENT-TYPE: text/xml\r\n"
                       "DATE: %s\r\n"
                       "LAST-MODIFIED: Sat, 01 Jan 2000 00:01:15 GMT\r\n"
                       "SERVER: Unspecified, UPnP/1.0, Unspecified\r\n"
                       "X-User-Agent: redsonic\r\n"
                       "CONNECTION: close\r\n"
                       "\r\n"
                       "%s" % (len(xml), date_str, xml))
            socket.send(message)
        elif data.find('SOAPACTION: "urn:Belkin:service:basicevent:1#SetBinaryState"') != -1:
            success = False
            if data.find('<BinaryState>1</BinaryState>') != -1:
                # on
                dbg("Responding to ON for %s" % self.name)
                success = self.action_handler.on()
            elif data.find('<BinaryState>0</BinaryState>') != -1:
                # off
                dbg("Responding to OFF for %s" % self.name)
                success = self.action_handler.off()
            else:
                dbg("Unknown Binary State request:")
                dbg(data)
            if success:
                # The echo is happy with the 200 status code and doesn't
                # appear to care about the SOAP response body
                soap = ""
                date_str = email.utils.formatdate(timeval=None, localtime=False, usegmt=True)
                message = ("HTTP/1.1 200 OK\r\n"
                           "CONTENT-LENGTH: %d\r\n"
                           "CONTENT-TYPE: text/xml charset=\"utf-8\"\r\n"
                           "DATE: %s\r\n"
                           "EXT:\r\n"
                           "SERVER: Unspecified, UPnP/1.0, Unspecified\r\n"
                           "X-User-Agent: redsonic\r\n"
                           "CONNECTION: close\r\n"
                           "\r\n"
                           "%s" % (len(soap), date_str, soap))
                socket.send(message)
        else:
            dbg(data)

    def on(self):
        return False

    def off(self):
        return True


# Since we have a single process managing several virtual UPnP devices,
# we only need a single listener for UPnP broadcasts. When a matching
# search is received, it causes each device instance to respond.
#
# Note that this is currently hard-coded to recognize only the search
# from the Amazon Echo for WeMo devices. In particular, it does not
# support the more common root device general search. The Echo
# doesn't search for root devices.

class UPnPBroadcastResponder(object):
    TIMEOUT = 0

    def __init__(self):
        self.devices = []

    def init_socket(self):
        ok = True
        self.ip = '239.255.255.250'
        self.port = 1900
        try:
            # This is needed to join a multicast group
            self.mreq = struct.pack("4sl", socket.inet_aton(self.ip), socket.INADDR_ANY)

            # Set up server socket
            self.ssock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self.ssock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            try:
                self.ssock.bind(('', self.port))
            except Exception as err:
                dbg("WARNING: Failed to bind %s: %d: %s" % (self.ip, self.port, err))
                ok = False

            try:
                self.ssock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, self.mreq)
            except Exception as err:
                dbg('WARNING: Failed to join multicast group: ' + err.strerror)
                ok = False

        except Exception as err:
            dbg("Failed to initialize UPnP sockets: " + err.strerror)
            return False
        if ok:
            dbg("Listening for UPnP broadcasts")

    def fileno(self):
        return self.ssock.fileno()

    def do_read(self, fileno):
        data, sender = self.recvfrom(1024)
        if data:
            if data.find('M-SEARCH') == 0 and data.find('urn:Belkin:device:**') != -1:
                for device in self.devices:
                    time.sleep(0.1)
                    device.respond_to_search(sender, 'urn:Belkin:device:**')
            else:
                pass

    # Receive network data
    def recvfrom(self, size):
        if self.TIMEOUT:
            self.ssock.setblocking(0)
            ready = select.select([self.ssock], [], [], self.TIMEOUT)[0]
        else:
            self.ssock.setblocking(1)
            ready = True

        try:
            if ready:
                return self.ssock.recvfrom(size)
            else:
                return False, False
        except Exception as e:
            dbg(e)
            return False, False

    def add_device(self, device):
        self.devices.append(device)
        dbg("UPnP broadcast listener: new device registered")


# This is an example handler class. The fauxmo class expects handlers to be
# instances of objects that have on() and off() methods that return True
# on success and False otherwise.
#
# This example class takes two full URLs that should be requested when an on
# and off command are invoked respectively. It ignores any return data.

# class rest_api_handler(object):
#    def __init__(self, on_cmd, off_cmd):
#        self.on_cmd = on_cmd
#        self.off_cmd = off_cmd
#
#    def on(self):
#        r = requests.get(self.on_cmd)
#        return r.status_code == 200
#
#    def off(self):
#        r = requests.get(self.off_cmd)
#        return r.status_code == 200

class GPIOSwitch(object):
    def __init__(self, pin_number):
        self.pin = pin_number
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin, GPIO.OUT)
        self.state = GPIO.input(pin_number)

    def on(self):
        if self.state == 0:
            GPIO.output(self.pin, 1)
            self.state = GPIO.input(self.pin)
            return True

    def off(self):
        if self.state == 1:
            GPIO.output(self.pin, 0)
            self.state = GPIO.input(self.pin)
            return True


class GPIOOneShot(object):
    def __init__(self, pin_number):
        self.pin = pin_number
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin, GPIO.OUT)
        self.state = GPIO.input(pin_number)

    def on(self):
        if self.state == 0:
            GPIO.output(self.pin, 1)
            time.sleep(2)
            GPIO.output(self.pin, 0)
            self.state = 1
        return True

    def off(self):
        if self.state == 1:
            GPIO.output(self.pin, 1)
            time.sleep(2)
            GPIO.output(self.pin, 0)
            self.state = 0
        return True


class GPIOAllOff(object):
    def __init__(self, pin_numbers):
        self.pins = pin_numbers

    def on(self):
        for pin in self.pins:
            if GPIOOneShot(pin).state == 0:
                GPIOOneShot(pin).on()
        return True

    def off(self):
        for pin in self.pins:
            if GPIOOneShot(pin).state == 1:
                GPIOOneShot(pin).off()
        return True


class GPIOReset(object):
    def __init__(self, pin_numbers):
        self.pins = pin_numbers

    def on(self):
        for pin in self.pins:
            GPIOOneShot(pin).off()
        return True

    def off(self):
        return True


# Each entry is a list with the following elements:
#
# name of the virtual switch
# object with 'on' and 'off' methods
# port # (optional; may be omitted)

# NOTE: As of 2015-08-17, the Echo appears to have a hard-coded limit of
# 16 switches it can control. Only the first 16 elements of the FAUXMOS
# list will be used.

FAUXMOS = [
    ['lounge room', GPIOOneShot(14), 58301],
    ['living room,', GPIOOneShot(15), 58302],
    ['bed one', GPIOOneShot(18), 58303],
    ['set cooling', GPIOOneShot(23), 58304],
    ['set heating', GPIOOneShot(24), 58305],
    ['increase temp one degree', GPIOOneShot(25), 58306],
    ['decrease temp one degree', GPIOOneShot(8), 58307],
    ['set twenty degrees', GPIOOneShot(7), 58308],
    ['set twenty one degrees', GPIOOneShot(1), 58309],
    ['set twenty two degrees', GPIOOneShot(12), 58310],
    ['set twenty three degrees', GPIOOneShot(16), 58311],
    ['set twenty four degrees', GPIOOneShot(20), 58312],
    ['system', GPIOAllOff([14, 15, 18]), 58313],  # only the pins that go to actual fancoils
    ['reset toggles', GPIOReset([14, 15, 18, 23, 24, 25, 8, 7, 1, 12, 16, 20]), 58314],  # all pins
]

CONFLICTS = [[],
             ]

if len(sys.argv) > 1 and sys.argv[1] == '-d':
    DEBUG = True

# Set up our singleton for polling the sockets for data ready
p = Poller()

# Set up our singleton listener for UPnP broadcasts
u = UPnPBroadcastResponder()
u.init_socket()

# Add the UPnP broadcast listener to the poller so we can respond
# when a broadcast is received.
p.add(u)

# Create our FauxMo virtual switch devices
for one_faux in FAUXMOS:
    if len(one_faux) == 2:
        # a fixed port wasn't specified, use a dynamic one
        one_faux.append(0)
    switch = Fauxmo(one_faux[0], u, p, None, one_faux[2], action_handler=one_faux[1])

dbg("Entering main loop\n")

try:
    status_led = GPIOSwitch(17)
    while True:
        try:
            # Allow time for a ctrl-c to stop the process
            p.poll(100)
            #dbg('on')
            status_led.on()
            time.sleep(0.1)
            #dbg('off')
            status_led.off()
        except Exception as e:
            raise e

finally:
    GPIO.cleanup()
