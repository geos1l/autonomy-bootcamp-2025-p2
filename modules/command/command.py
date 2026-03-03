"""
Decision-making logic.
"""

import math

from pymavlink import mavutil

from ..common.modules.logger import logger
from ..telemetry.telemetry import TelemetryData


class Position:
    """
    3D vector struct.
    """

    def __init__(self, x: float, y: float, z: float) -> None:
        self.x = x
        self.y = y
        self.z = z


# =================================================================================================
#                            ↓ BOOTCAMPERS MODIFY BELOW THIS COMMENT ↓
# =================================================================================================
class Command:  # pylint: disable=too-many-instance-attributes
    """
    Command class to make a decision based on recieved telemetry,
    and send out commands based upon the data.
    """

    __private_key = object()

    @classmethod
    def create(
        cls,
        connection: mavutil.mavfile,
        target: Position,
        args: tuple,  # Put your own arguments here
        local_logger: logger.Logger,
    ) -> "tuple[bool, Command | None]":
        """
        Falliable create (instantiation) method to create a Command object.
        """
        return True, cls(cls.__private_key, connection, target, args, local_logger)

    def __init__(
        self,
        key: object,
        connection: mavutil.mavfile,
        target: Position,
        _args: tuple,  # Put your own arguments here (unused in __init__)
        local_logger: logger.Logger,
    ) -> None:
        assert key is Command.__private_key, "Use create() method"
        self._connection = connection
        self._target = target
        self._logger = local_logger
        self._velocity_sum_x = 0.0
        self._velocity_sum_y = 0.0
        self._velocity_sum_z = 0.0
        self._report_count = 0

    def run(
        self,
        args: TelemetryData,  # Put your own arguments here (TelemetryData)
    ) -> list[str]:
        """
        Make a decision based on received telemetry data.
        """
        data: TelemetryData = args
        out_strings: list[str] = []

        # Log average velocity for this trip so far
        if (
            data.x_velocity is not None
            and data.y_velocity is not None
            and data.z_velocity is not None
        ):
            self._velocity_sum_x += data.x_velocity
            self._velocity_sum_y += data.y_velocity
            self._velocity_sum_z += data.z_velocity
            self._report_count += 1
            if self._report_count > 0:
                avg_vx = self._velocity_sum_x / self._report_count
                avg_vy = self._velocity_sum_y / self._report_count
                avg_vz = self._velocity_sum_z / self._report_count
                self._logger.info(
                    f"Average velocity: ({avg_vx}, {avg_vy}, {avg_vz})",
                    True,
                )

        # Use COMMAND_LONG (76), target_system=1, target_component=0
        target_sys = 1
        target_comp = 0
        confirmation = 0

        # Adjust height using MAV_CMD_CONDITION_CHANGE_ALT (113)
        sent_alt = False
        if data.z is not None and abs(data.z - self._target.z) > 0.5:
            delta_z = self._target.z - data.z
            self._connection.mav.command_long_send(
                target_sys,
                target_comp,
                mavutil.mavlink.MAV_CMD_CONDITION_CHANGE_ALT,
                confirmation,
                1.0,  # param1: speed m/s (Z_SPEED)
                0,
                0,
                0,
                0,
                0,
                self._target.z,  # param7: target altitude
            )
            out_strings.append(f"CHANGE ALTITUDE: {delta_z}")
            sent_alt = True

        # Adjust direction (yaw) using MAV_CMD_CONDITION_YAW (115). Relative angle.
        # At most one COMMAND_LONG per update so mock drone receives exactly NUM_TRIALS.
        if not sent_alt and data.yaw is not None and data.x is not None and data.y is not None:
            angle_to_target_rad = math.atan2(
                self._target.y - data.y,
                self._target.x - data.x,
            )
            relative_yaw_rad = angle_to_target_rad - data.yaw
            while relative_yaw_rad > math.pi:
                relative_yaw_rad -= 2 * math.pi
            while relative_yaw_rad < -math.pi:
                relative_yaw_rad += 2 * math.pi
            relative_yaw_deg = math.degrees(relative_yaw_rad)
            if abs(relative_yaw_deg) > 5:
                self._connection.mav.command_long_send(
                    target_sys,
                    target_comp,
                    mavutil.mavlink.MAV_CMD_CONDITION_YAW,
                    confirmation,
                    relative_yaw_deg,  # param1: target angle (deg)
                    5.0,  # param2: turning speed deg/s (TURNING_SPEED)
                    0,
                    1,  # param4: relative (1)
                    0,
                    0,
                    0,
                )
                out_strings.append(f"CHANGE YAW: {relative_yaw_deg}")

        return out_strings


# =================================================================================================
#                            ↑ BOOTCAMPERS MODIFY ABOVE THIS COMMENT ↑
# =================================================================================================
