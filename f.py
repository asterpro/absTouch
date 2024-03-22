import _tkinter
import contextlib
import os
import pkg_resources
import subprocess as sp
import sys

import evdev
import pyudev


@contextlib.contextmanager
def lock_pointer_x11(devname):
    sp.call(['xinput', 'disable', devname])
    try:
        yield
    finally:
        sp.call(['xinput', 'enable', devname])


@contextlib.contextmanager
def lock_pointer_wayland():
    prev_value = sp.check_output(['gsettings', 'get', 'org.gnome.desktop.peripherals.touchpad', 'send-events']).strip()

    # Fix for arch based distros
    if prev_value == '':
        prev_value = "'enabled'"

    if prev_value not in (b"'enabled'", b"'disabled'", b"'disabled-on-external-mouse'"):
        print(f'Unexpected touchpad state: "{prev_value.decode()}", are you using Gnome?', file=sys.stderr)
        exit(1)

    sp.call(['dconf', 'write', '/org/gnome/desktop/peripherals/touchpad/send-events', "'disabled'"])
    try:
        yield
    finally:
        sp.call(['dconf', 'write', '/org/gnome/desktop/peripherals/touchpad/send-events', prev_value])



def get_touchpads(udev):
    for device in udev.list_devices(ID_INPUT_TOUCHPAD='1'):
        if device.device_node is not None and device.device_node.rpartition('/')[2].startswith('event'):
            yield device


def get_device_name(dev):
    while dev is not None:
        name = dev.properties.get('NAME')
        if name:
            return name
        else:
            dev = next(dev.ancestors, None)


def permission_error():
    print('Failed to access touchpad!', file=sys.stderr)
    if sys.stdin.isatty():
        print('Touchpad access is currently restricted. Would you like to unrestrict it?', file=sys.stderr)
        response = input('[Yes]/no: ')
        if response.lower() in ('y', 'ye', 'yes', 'ok', 'sure', ''):
            sp.call(['pkexec', pkg_resources.resource_filename('fingerpaint', 'data/fix_permissions.sh')])
        else:
            print('Canceled.', file=sys.stderr)

    exit(1)


def get_touchpad(udev):
    for device in get_touchpads(udev):
        dev_name = get_device_name(device).strip('"')
        print('Using touchpad:', dev_name, file=sys.stderr)
        try:
            return evdev.InputDevice(device.device_node), dev_name
        except PermissionError:
            permission_error()
    return None, None

def this(events, devname):
    try:
        if os.environ['XDG_SESSION_TYPE'] == 'wayland':
            lock_pointer = lock_pointer_wayland()
        else:
            lock_pointer = lock_pointer_x11(devname)

        with lock_pointer:
            while True:
                lines = next(events)
                if (lines != []):
                    print(lines)
    except (KeyboardInterrupt, _tkinter.TclError):
        del events
        exit(0)


def main():
    udev = pyudev.Context()
    touchpad, devname = get_touchpad(udev)
    if touchpad is None:
        print('No touchpad found', file=sys.stderr)
        exit(1)
    x_absinfo = touchpad.absinfo(evdev.ecodes.ABS_X)
    y_absinfo = touchpad.absinfo(evdev.ecodes.ABS_Y)
    val_range = (x_absinfo.max - x_absinfo.min, y_absinfo.max - y_absinfo.min)
    print(f"{x_absinfo} \n {y_absinfo}\n")

    def handler_loop():
        last_pos = (-1, -1)
        curr_pos = (-1, -1)
        wip_pos = (-1, -1)
        while True:
            event = touchpad.read_one()
            if event:
                if event.type == evdev.ecodes.EV_ABS:
                    if event.code == evdev.ecodes.ABS_X:
                        wip_pos = ((event.value - x_absinfo.min) / (x_absinfo.max - x_absinfo.min), wip_pos[1])
                    if event.code == evdev.ecodes.ABS_Y:
                        wip_pos = (wip_pos[0], (event.value - y_absinfo.min) / (y_absinfo.max - y_absinfo.min))
                if event.type == evdev.ecodes.EV_KEY:
                    if event.code == evdev.ecodes.BTN_TOUCH and event.value == 0:
                        wip_pos = (-1, -1)
                    if (event.code == evdev.ecodes.BTN_LEFT or event.code == evdev.ecodes.BTN_RIGHT) \
                            and event.value == 1:
                        raise KeyboardInterrupt()
                if event.type == evdev.ecodes.EV_SYN:
                    curr_pos = wip_pos

            if last_pos != curr_pos:
                if (last_pos[0] == -1 or last_pos[1] == -1) and curr_pos[0] != -1 and curr_pos[1] != -1:
                    # Work with light taps
                    last_pos = curr_pos
                if last_pos[0] != -1 and last_pos[1] != -1 and curr_pos[0] != -1 and curr_pos[1] != -1:
                    yield [(curr_pos)]
                else:
                    yield []
                last_pos = curr_pos
            else:
                yield []

    this(handler_loop(), devname)
    del touchpad

main()