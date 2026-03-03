"""
Telemetry gathering logic.
"""

import time

from pymavlink import mavutil

from ..common.modules.logger import logger


class TelemetryData:  # pylint: disable=too-many-instance-attributes
    """
    Python struct to represent Telemtry Data. Contains the most recent attitude and position reading.
    """

    def __init__(
        self,
        time_since_boot: int | None = None,  # ms
        x: float | None = None,  # m
        y: float | None = None,  # m
        z: float | None = None,  # m
        x_velocity: float | None = None,  # m/s
        y_velocity: float | None = None,  # m/s
        z_velocity: float | None = None,  # m/s
        roll: float | None = None,  # rad
        pitch: float | None = None,  # rad
        yaw: float | None = None,  # rad
        roll_speed: float | None = None,  # rad/s
        pitch_speed: float | None = None,  # rad/s
        yaw_speed: float | None = None,  # rad/s
    ) -> None:
        self.time_since_boot = time_since_boot
        self.x = x
        self.y = y
        self.z = z
        self.x_velocity = x_velocity
        self.y_velocity = y_velocity
        self.z_velocity = z_velocity
        self.roll = roll
        self.pitch = pitch
        self.yaw = yaw
        self.roll_speed = roll_speed
        self.pitch_speed = pitch_speed
        self.yaw_speed = yaw_speed

    def __str__(self) -> str:
        return f"""{{
            time_since_boot: {self.time_since_boot},
            x: {self.x},
            y: {self.y},
            z: {self.z},
            x_velocity: {self.x_velocity},
            y_velocity: {self.y_velocity},
            z_velocity: {self.z_velocity},
            roll: {self.roll},
            pitch: {self.pitch},
            yaw: {self.yaw},
            roll_speed: {self.roll_speed},
            pitch_speed: {self.pitch_speed},
            yaw_speed: {self.yaw_speed}
        }}"""


# =================================================================================================
#                            ↓ BOOTCAMPERS MODIFY BELOW THIS COMMENT ↓
# =================================================================================================
class Telemetry:
    """
    Telemetry class to read position and attitude (orientation).
    """

    __private_key = object()

    @classmethod
    def create(
        cls,
        connection: mavutil.mavfile,
        args: tuple,  # Put your own arguments here
        local_logger: logger.Logger,
    ) -> "tuple[bool, Telemetry | None]":
        """
        Falliable create (instantiation) method to create a Telemetry object.
        """
        return True, cls(cls.__private_key, connection, args, local_logger)

    def __init__(
        self,
        key: object,
        connection: mavutil.mavfile,
        _args: tuple,  # Put your own arguments here (unused in __init__)
        local_logger: logger.Logger,
    ) -> None:
        assert key is Telemetry.__private_key, "Use create() method"
        self._connection = connection
        self._logger = local_logger

    def run(
        self,
        _args: tuple,  # Put your own arguments here (unused)
    ) -> TelemetryData | None:
        """
        Receive LOCAL_POSITION_NED and ATTITUDE messages from the drone,
        combining them together to form a single TelemetryData object.
        """
        timeout_s = 1.0
        deadline = time.time() + timeout_s
        latest_attitude = None
        latest_position = None

        while time.time() < deadline:
            remaining = deadline - time.time()
            msg = self._connection.recv_match(
                type=["ATTITUDE", "LOCAL_POSITION_NED"],
                blocking=True,
                timeout=min(0.2, remaining),
            )
            if msg is None:
                continue
            if msg.get_type() == "ATTITUDE":
                latest_attitude = msg
            elif msg.get_type() == "LOCAL_POSITION_NED":
                latest_position = msg

            if latest_attitude is not None and latest_position is not None:
                time_boot_ms = max(
                    latest_attitude.time_boot_ms,
                    latest_position.time_boot_ms,
                )
                return TelemetryData(
                    time_since_boot=time_boot_ms,
                    x=latest_position.x,
                    y=latest_position.y,
                    z=latest_position.z,
                    x_velocity=latest_position.vx,
                    y_velocity=latest_position.vy,
                    z_velocity=latest_position.vz,
                    roll=latest_attitude.roll,
                    pitch=latest_attitude.pitch,
                    yaw=latest_attitude.yaw,
                    roll_speed=latest_attitude.rollspeed,
                    pitch_speed=latest_attitude.pitchspeed,
                    yaw_speed=latest_attitude.yawspeed,
                )

        self._logger.error("Telemetry timeout: did not receive both messages in 1s", True)
        return None


# =================================================================================================
#                            ↑ BOOTCAMPERS MODIFY ABOVE THIS COMMENT ↑
# =================================================================================================
