# SPDX-License-Identifier: MIT
"""Lap score receiver.

Receive lap score updates from gemini or prism lapscore attached
via serial port.

"""

import threading
import logging
import serial
import sys
from metarace import unt4
from time import sleep

# module logger
_log = logging.getLogger('lapscore')
_log.setLevel(logging.DEBUG)

# constants
_BAUD = 9600
_TIMEOUT = 2
_ENCODING = 'ascii'
_MAXMSG = 64
_SOH = unt4.SOH.decode('ascii')


class lapscore(threading.Thread):
    """Lapscore receiver thread."""

    def __init__(self, port=None):
        threading.Thread.__init__(self, daemon=True)
        self._port = port
        self._running = False
        self._cb = None

    def exit(self):
        """Request thread termination."""
        self._running = False
        self._port = None
        self._cb = None

    def setcb(self, func=None):
        """Set lap update callback."""
        self._cb = func

    def _parselaps(self, msg):
        """Decode UNT4 from msg and return laps if relevant"""
        ret = None
        lidx = msg.find(_SOH)
        #_log.debug('RECV: %r', msg)
        if lidx >= 0:
            umsg = unt4.unt4(msg[lidx:])
            if umsg.erp:  # general clearing
                ret = ''
                _log.debug('general clearing')
            else:
                if umsg.prefix == 20 and umsg.header == 'S00':
                    # GEMINI
                    if umsg.text.startswith('\x08'):
                        lapline = umsg.text[1:]
                        if not lapline.startswith('\n'):
                            ret = lapline[0:3].strip()
                            _log.debug('gemini lap = %r', ret)
                        #else:  # gemini line 2+
                        #pass
                elif umsg.header == 'S0SD0':
                    # prism LED clearing
                    ret = ''
                    _log.debug('prism clear')
                elif umsg.header == 'S0SLC':
                    # prism LED lap score
                    ret = umsg.text.strip()
                    _log.debug('prism lap = %r', ret)
                else:
                    _log.debug('Unknown lapscore: hdr=%r, txt=%r', umsg.header,
                               umsg.text)
        else:
            _log.debug('Invalid message: %r', msg)
        return ret

    def _read(self, port):
        """Watch serial port for lap score updates."""
        buf = bytearray()
        while self._running:
            c = port.read(1)
            if c:
                buf.extend(c)
                if c[0] == unt4.EOT[0] or len(buf) > _MAXMSG:
                    msg = buf.decode(_ENCODING, 'ignore').lstrip()
                    buf.clear()
                    if msg:
                        laps = self._parselaps(msg)
                        if laps is not None and self._cb is not None:
                            self._cb(laps)

    def run(self):
        _log.debug('Starting lapscore[%s]', self.native_id)
        if self._port is not None:
            self._running = True
            while self._running:
                sleep(_TIMEOUT)
                try:
                    if self._cb is not None:
                        self._cb(None)  # send initial empty value
                    with serial.Serial(self._port, _BAUD,
                                       timeout=_TIMEOUT) as s:
                        self._read(s)
                except IOError as e:
                    self._s = None
                    _log.info('IO Error[%s]: %s', self.native_id, e)
                except Exception as e:
                    self._s = None
                    _log.info('%s[%s]: %s', e.__class__.__name__,
                               self.native_id, e)
        else:
            _log.debug('Serial port not set')
        _log.debug('Exiting lapscore[%s]', self.native_id)
