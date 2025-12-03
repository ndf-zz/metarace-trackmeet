# SPDX-License-Identifier: MIT
"""DHI scoreboard sender class.

This module provides a thread object which collects
and dispatches DHI messages intended for a Galactica or
Caprica scoreboard.

"""

import threading
import queue
import logging
import socket
import serial

from metarace import sysconf
from metarace import unt4
from metarace import strops

# Caprica encoding is UTF-8, Galactica is undefined - probably CP1252
_DEFENCODING = 'utf-8'
_DEFLINELEN = 24
_DEFPAGELEN = 7
_DEFBAUDRATE = 115200
_DEFPORT = 2004 - 58

# module log object
_log = logging.getLogger('sender')
_log.setLevel(logging.DEBUG)

_CONFIG_SCHEMA = {
    'ttype': {
        'prompt': 'Text Scoreboard Sender Options',
        'control': 'section',
    },
    'scoreboard': {
        'prompt': 'Type:',
        'control': 'choice',
        'options': {
            'dhi': 'Caprica/DHI',
            'dak': 'Daktronics (DGV)',
        },
        'default': 'dhi',
    },
    'portspec': {
        'prompt': 'Default Port:',
        'default': 'TCP:localhost:1946',
    },
    'linelen': {
        'prompt': 'Line Length:',
        'control': 'short',
        'subtext': '(Characters)',
        'type': 'int',
        'default': 24,
    },
    'pagelen': {
        'prompt': 'Page Length:',
        'control': 'short',
        'subtext': '(Lines)',
        'type': 'int',
        'default': 7,
    },
    'encoding': {
        'prompt': 'Encoding:',
        'control': 'short',
        'default': 'utf-8'
    },
    'baudrate': {
        'prompt': 'Serial Baud:',
        'control': 'short',
        'type': 'int',
    },
}

# Exported overlay messages
OVERLAY_ON = unt4.unt4(header='OVERLAY ON')
OVERLAY_OFF = unt4.unt4(header='OVERLAY OFF')
OVERLAY_MATRIX = unt4.unt4(header='OVERLAY 00')
OVERLAY_CLOCK = unt4.unt4(header='OVERLAY 01')
OVERLAY_IMAGE = unt4.unt4(header='OVERLAY 02')
OVERLAY_BLANK = unt4.unt4(header='OVERLAY 03')
OVERLAY_BRIDGE = unt4.unt4(header='OVERLAY 04')


class serialport:
    """Serial port wrapper"""

    def __init__(self, addr, baudrate):
        """Constructor.

        Parameters:

          addr -- serial device filename
          baudrate -- serial line speed

        """
        _log.debug('Serial connection %s @ %d baud.', addr, baudrate)
        self._s = serial.Serial(addr, baudrate, rtscts=False)
        self.send = self._s.write

    def sendall(self, buf):
        """Send all of buf to port."""
        msglen = len(buf)
        sent = 0
        while sent < msglen:
            out = self.send(buf[sent:])
            sent += out

    def close(self):
        """Shutdown socket object."""
        try:
            self._s.close()
        except Exception:
            pass


class scbport:
    """Scoreboard communication port object."""

    def __init__(self, addr, protocol):
        """Constructor.

        Parameters:

          addr -- socket style 2-tuple (host, port)
          protocol -- one of socket.SOCK_STREAM or socket.SOCK_DGRAM

        """
        self._s = socket.socket(socket.AF_INET, protocol)
        if protocol == socket.SOCK_STREAM:
            try:
                self._s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._s.setsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT,
                                   5000)
            except Exception as e:
                _log.debug('%s setting TCP_NODELAY/TCP_USER_TIMEOUT: %s',
                           e.__class__.__name__, e)
            _log.debug('Opening TCP socket %s', repr(addr))
        else:  # assume Datagram (UDP)
            # enable broadcast send
            self._s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            _log.debug('Opening UDP socket %s', repr(addr))
        self._s.connect(addr)
        self.send = self._s.send

    def sendall(self, buf):
        """Send all of buf to port."""
        msglen = len(buf)
        sent = 0
        while sent < msglen:
            out = self.send(buf[sent:])
            if out == 0:
                raise socket.error('DHI sender socket broken')
            sent += out

    def close(self):
        """Shutdown socket object."""
        try:
            self._s.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass


def mkport(port):
    """Create a new scbport object.

    port is a string specifying the address as follows:

        [PROTOCOL:]ADDRESS[:PORT]

    Where:

        PROTOCOL :: TCP or UDP	(optional)
        ADDRESS :: hostname or IP address or device file
        PORT :: port name or number (optional)

    """
    nprot = socket.SOCK_STREAM
    naddr = 'localhost'
    nport = _DEFPORT

    # import system defaults if required
    if port.upper() == 'DEFAULT':
        defport = ''
        if sysconf.has_option('sender', 'portspec'):
            defport = sysconf.get('sender', 'portspec')
        if defport:
            port = defport
        else:
            port = 'TCP:localhost:' + str(_DEFPORT)

    if port.upper() == 'DEBUG':  # force use of the hardcoded UDP endpoint
        nprot = socket.SOCK_DGRAM
        _log.debug('Using debug port: UDP:%s:%d', naddr, nport)
    else:
        vels = ['TCP', 'localhost', str(_DEFPORT)]
        aels = port.translate(strops.PRINT_UTRANS).strip().split(':')
        if len(aels) == 3:
            vels[0] = aels[0].upper()
            vels[1] = aels[1]
            vels[2] = aels[2]
        elif len(aels) == 2:
            if aels[0].upper() in ['TCP', 'UDP']:
                # assume PROT:ADDR
                vels[0] = aels[0].upper()
                vels[1] = aels[1]
            else:
                vels[1] = aels[0]
                vels[2] = aels[1]
        elif len(aels) == 1:
            vels[1] = aels[0]
        else:
            raise socket.error('Invalid port specification string')

        # 'import' the vels...
        if vels[0] == 'TCP':
            nprot = socket.SOCK_STREAM
        elif vels[0] == 'UDP':
            nprot = socket.SOCK_DGRAM
        else:
            raise socket.error('Invalid protocol specified.')
        naddr = vels[1]
        # override port if supplied
        if vels[2].isdigit():
            nport = int(vels[2])
        else:
            nport = socket.getservbyname(vels[2])

    if '/dev/' in naddr:
        # assume device file for a serial port
        baud = _DEFBAUDRATE
        if sysconf.has_option('sender', 'baudrate'):
            baud = strops.confopt_posint(sysconf.get('sender', 'baudrate'),
                                         _DEFBAUDRATE)
        return serialport(naddr, baud)
    else:
        return scbport((naddr, nport), nprot)


def sender(port=None):
    """Return a sender of the configured type"""
    stype = 'dhi'
    if sysconf.has_option('sender', 'scoreboard'):
        ntype = sysconf.get('sender', 'scoreboard')
        if ntype in ('dhi', 'dak'):
            stype = ntype
    if stype == 'dak':
        return daksender(port)
    else:
        return basesender(port)


class basesender(threading.Thread):
    """Caprica/Galactica DHI sender thread."""

    def clrall(self):
        """Clear all lines in DHI database."""
        self.sendmsg(unt4.GENERAL_CLEARING)

    def clrline(self, line):
        """Clear the specified line in DHI database."""
        self.sendmsg(unt4.unt4(xx=0, yy=int(line), erl=True))

    def setline(self, line, msg):
        """Set the specified DHI database line to msg."""
        msg = strops.truncpad(msg, self.linelen, 'l', False)
        self.sendmsg(unt4.unt4(xx=0, yy=int(line), erl=True, text=msg))

    def flush(self):
        """Send an empty update to force timeout clock to zero."""
        self.sendmsg(unt4.GENERAL_EMPTY)

    def linefill(self, line, char='_'):
        """Use char to fill the specified line."""
        msg = char * self.linelen
        self.sendmsg(unt4.unt4(xx=0, yy=int(line), text=msg))

    def postxt(self, line, oft, msg):
        """Position msg at oft on line in DHI database."""
        self.sendmsg(unt4.unt4(xx=int(oft), yy=int(line), text=msg))

    def setoverlay(self, newov):
        """Request overlay newov to be displayed on the scoreboard."""
        self.sendmsg(newov)

    def __init__(self, port=None):
        """Constructor."""
        threading.Thread.__init__(self, daemon=True)
        self._port = None
        self._encoding = _DEFENCODING

        self.linelen = _DEFLINELEN
        self.pagelen = _DEFPAGELEN

        self._ignore = False
        self._queue = queue.Queue()
        self._running = False

        if port is not None:
            self.setport(port)

    def sendmsg(self, unt4msg=None):
        """Pack and send a unt4 message to the DHI."""
        self._queue.put_nowait(('MSG', unt4msg.pack()))

    def write(self, msg=None):
        """Send the provided raw msg to the DHI."""
        self._queue.put_nowait(('MSG', msg))

    def exit(self, msg=None):
        """Request thread termination."""
        self._running = False
        self._queue.put_nowait(('EXIT', msg))

    def wait(self):
        """Suspend calling thread until cqueue is empty."""
        self._queue.join()

    def setport(self, port=None):
        """Dump command queue contents and (re)open DHI port.

        Specify hostname and port for TCP connection as follows:

            tcp:hostname:16372

        Or use DEBUG for a fallback UDP socket:

	    UDP:localhost:5060

        """
        try:
            while True:
                self._queue.get_nowait()
                self._queue.task_done()
        except queue.Empty:
            pass
        self._queue.put_nowait(('PORT', port))

    def set_ignore(self, ignval=False):
        """Set or clear the ignore flag."""
        self._ignore = bool(ignval)

    def connected(self):
        """Return true if SCB connected."""
        return self._port is not None and self._running

    def run(self):

        # import site defaults from sysconf
        if sysconf.has_option('sender', 'linelen'):
            self.linelen = sysconf.get('sender', 'linelen')
        if sysconf.has_option('sender', 'pagelen'):
            self.pagelen = sysconf.get('sender', 'pagelen')
        if sysconf.has_option('sender', 'encoding'):
            self._encoding = sysconf.get('sender', 'encoding')

        self._running = True
        _log.debug('Starting')
        while self._running:
            m = self._queue.get()
            self._queue.task_done()
            try:
                if m[0] == 'MSG' and not self._ignore and self._port:
                    #_log.debug('SEND: ' + repr(m[1]))
                    self._port.sendall(m[1].encode(self._encoding, 'replace'))
                elif m[0] == 'EXIT':
                    _log.debug('Request to close: %s', m[1])
                    self._running = False
                elif m[0] == 'PORT':
                    if self._port is not None:
                        self._port.close()
                        self._port = None
                    if m[1] not in [None, '', 'none', 'NULL']:
                        _log.debug('Re-Connect port: %s', m[1])
                        self._port = mkport(m[1])
                    else:
                        _log.debug('Not connected.')

            except IOError as e:
                _log.error('IO Error: %s', e)
                if self._port is not None:
                    self._port.close()
                self._port = None
            except Exception as e:
                _log.error('%s: %s', e.__class__.__name__, e)
        if self._port is not None:
            self._port.close()
        _log.info('Exiting')


class daksender(basesender):

    def _daksum(self, msg):
        sum = 0x00
        for c in msg.encode(self._encoding, 'replace'):
            sum += c
        return '{0:02X}'.format(sum & 0xff)

    def sendmsg(self, unt4msg=None):
        """Pack and send a DAK (Venus) message."""
        msg = None
        oft = 0
        text = ''
        if unt4msg.erp:
            # emit full page of spaces
            text = ' ' * self.linelen * self.pagelen
        elif unt4msg.xx is not None and unt4msg.yy is not None and unt4msg.text:
            # place chars at board offset
            oft = unt4msg.yy * self.linelen + unt4msg.xx
            text = unt4msg.text.replace('\u2006', ' ')
        else:
            pass
        control = '004010%04d' % (oft, )
        msg = ''.join((
            '20000000',
            chr(unt4.SOH[0]),
            control,
            chr(unt4.STX[0]),
            text,
            chr(unt4.EOT[0]),
        ))
        ob = ''.join((
            chr(unt4.SYN[0]),
            msg,
            self._daksum(msg),
            chr(unt4.ETB[0]),
        ))
        self._queue.put_nowait(('MSG', ob))

    def setoverlay(self, newov):
        """Ignore overlay change."""
        pass

    def flush(self):
        """Ignore flush."""
        pass

    def postxt(self, line, oft, msg):
        """Position msg at oft on line."""
        if oft < self.linelen:
            if line > 1:
                msg = msg.upper()
            msg = msg[0:(self.linelen - oft)]
            self.sendmsg(unt4.unt4(xx=int(oft), yy=int(line), text=msg))

    def setline(self, line, msg):
        """Set the specified line to msg."""
        if line > 1:
            msg = msg.upper()
        msg = strops.truncpad(msg, self.linelen, 'l', False)
        self.sendmsg(unt4.unt4(xx=0, yy=int(line), text=msg))

    def clrline(self, line):
        """Clear the specified line."""
        msg = ' ' * self.linelen
        self.sendmsg(unt4.unt4(xx=0, yy=int(line), text=msg))
