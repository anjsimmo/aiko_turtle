#!/usr/bin/env python3
# TurtleRobot Interface shared by the virtual robot Actor and its clients
# (chat bot, CLI, agents). Mirrors the June 2026 Colab tutorial notebooks.

from abc import abstractmethod

import aiko_services as aiko

ROBOT_NAME = "anj_turtle_robot"
_VERSION = 0
ROBOT_PROTOCOL = f"{aiko.SERVICE_PROTOCOL_AIKO}/turtle_robot:{_VERSION}"


class TurtleRobot(aiko.Actor):
    @abstractmethod
    def action(self, value):
        pass

    @abstractmethod
    def forward(self, value):
        pass

    @abstractmethod
    def backward(self, value):
        pass

    @abstractmethod
    def left(self, value):
        pass

    @abstractmethod
    def right(self, value):
        pass


def get_robot_service_filter(name=ROBOT_NAME):
    return aiko.ServiceFilter("*", name, "*", "*", "*", "*")
