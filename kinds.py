# The robot kinds and interfaces, from the robots/ package (one module per
# robot interface).  This module is the small API the rest of the code
# uses; the registry itself is robots/__init__.py.

import robots
from robots import INTERFACES, KINDS, DEFAULT_KIND, kind_axes, resolve   # noqa: F401
from robots.base import STATUS_REAL, STATUS_LEGACY, STATUS_PROPOSED     # noqa: F401

AXIS_NAMES = ("forward", "left", "up")


def kind_interfaces(kind):
    """The interfaces a body may speak, default first"""
    return list(KINDS.get(kind, KINDS[DEFAULT_KIND])["interfaces"])


def default_interface(kind):
    return robots.default_interface(kind)


def supports(kind, method, interface=None):
    interface = interface or default_interface(kind)
    return robots.supports(interface, kind, method)


def kind_commands(kind, interface=None):
    """The chat command examples of a body's interface"""
    interface = interface or default_interface(kind)
    return [example for example, _ in robots.commands(interface, kind)]


def describe():
    """For /api/kinds and the page"""
    return robots.describe_kinds()


def describe_interfaces():
    return robots.describe_interfaces()


def describe_interface(name, kind=None):
    return robots.describe_interface(name, kind)
