"""
Bootcamp F2025

Main process to setup and manage all the other working processes
"""

import multiprocessing as mp
import queue
import time

from pymavlink import mavutil

from modules.common.modules.logger import logger
from modules.common.modules.logger import logger_main_setup
from modules.common.modules.read_yaml import read_yaml
from modules.command import command
from modules.command import command_worker
from modules.heartbeat import heartbeat_receiver_worker
from modules.heartbeat import heartbeat_sender_worker
from modules.telemetry import telemetry_worker
from utilities.workers import queue_proxy_wrapper
from utilities.workers import worker_controller
from utilities.workers import worker_manager


# MAVLink connection
CONNECTION_STRING = "tcp:localhost:12345"

# =================================================================================================
#                            ↓ BOOTCAMPERS MODIFY BELOW THIS COMMENT ↓
# =================================================================================================
# Set queue max sizes (<= 0 for infinity; positive required for fill_and_drain)
HEARTBEAT_RECEIVER_TO_MAIN_QUEUE_MAX_SIZE = 10
TELEMETRY_TO_COMMAND_QUEUE_MAX_SIZE = 10
COMMAND_TO_MAIN_QUEUE_MAX_SIZE = 10

# Set worker counts
HEARTBEAT_SENDER_COUNT = 1
HEARTBEAT_RECEIVER_COUNT = 1
TELEMETRY_WORKER_COUNT = 1
COMMAND_WORKER_COUNT = 1

# Any other constants
TARGET_POSITION = command.Position(0, 0, 30)
MAIN_LOOP_DURATION_S = 100

# =================================================================================================
#                            ↑ BOOTCAMPERS MODIFY ABOVE THIS COMMENT ↑
# =================================================================================================


def main() -> int:
    """
    Main function.
    """
    # Configuration settings
    result, config = read_yaml.open_config(logger.CONFIG_FILE_PATH)
    if not result:
        print("ERROR: Failed to load configuration file")
        return -1

    # Get Pylance to stop complaining
    assert config is not None

    # Setup main logger
    result, main_logger, _ = logger_main_setup.setup_main_logger(config)
    if not result:
        print("ERROR: Failed to create main logger")
        return -1

    # Get Pylance to stop complaining
    assert main_logger is not None

    # Create a connection to the drone. Assume that this is safe to pass around to all processes
    # In reality, this will not work, but to simplify the bootamp, preetend it is allowed
    # To test, you will run each of your workers individually to see if they work
    # (test "drones" are provided for you test your workers)
    # NOTE: If you want to have type annotations for the connection, it is of type mavutil.mavfile
    connection = mavutil.mavlink_connection(CONNECTION_STRING)
    connection.wait_heartbeat(timeout=30)  # Wait for the "drone" to connect

    # =============================================================================================
    #                          ↓ BOOTCAMPERS MODIFY BELOW THIS COMMENT ↓
    # =============================================================================================
    # Create a worker controller
    controller = worker_controller.WorkerController()

    # Create a multiprocess manager for synchronized queues
    mp_manager = mp.Manager()

    # Create queues
    heartbeat_receiver_to_main = queue_proxy_wrapper.QueueProxyWrapper(
        mp_manager, HEARTBEAT_RECEIVER_TO_MAIN_QUEUE_MAX_SIZE
    )
    telemetry_to_command = queue_proxy_wrapper.QueueProxyWrapper(
        mp_manager, TELEMETRY_TO_COMMAND_QUEUE_MAX_SIZE
    )
    command_to_main = queue_proxy_wrapper.QueueProxyWrapper(
        mp_manager, COMMAND_TO_MAIN_QUEUE_MAX_SIZE
    )

    # Create worker properties for each worker type (what inputs it takes, how many workers)
    # Heartbeat sender
    result, heartbeat_sender_properties = worker_manager.WorkerProperties.create(
        count=HEARTBEAT_SENDER_COUNT,
        target=heartbeat_sender_worker.heartbeat_sender_worker,
        work_arguments=(connection,),
        input_queues=[],
        output_queues=[],
        controller=controller,
        local_logger=main_logger,
    )
    if not result:
        print("ERROR: Failed to create heartbeat sender properties")
        return -1
    assert heartbeat_sender_properties is not None

    # Heartbeat receiver
    result, heartbeat_receiver_properties = worker_manager.WorkerProperties.create(
        count=HEARTBEAT_RECEIVER_COUNT,
        target=heartbeat_receiver_worker.heartbeat_receiver_worker,
        work_arguments=(connection,),
        input_queues=[],
        output_queues=[heartbeat_receiver_to_main],
        controller=controller,
        local_logger=main_logger,
    )
    if not result:
        print("ERROR: Failed to create heartbeat receiver properties")
        return -1
    assert heartbeat_receiver_properties is not None

    # Telemetry
    result, telemetry_properties = worker_manager.WorkerProperties.create(
        count=TELEMETRY_WORKER_COUNT,
        target=telemetry_worker.telemetry_worker,
        work_arguments=(connection,),
        input_queues=[],
        output_queues=[telemetry_to_command],
        controller=controller,
        local_logger=main_logger,
    )
    if not result:
        print("ERROR: Failed to create telemetry properties")
        return -1
    assert telemetry_properties is not None

    # Command
    result, command_properties = worker_manager.WorkerProperties.create(
        count=COMMAND_WORKER_COUNT,
        target=command_worker.command_worker,
        work_arguments=(connection, TARGET_POSITION),
        input_queues=[telemetry_to_command],
        output_queues=[command_to_main],
        controller=controller,
        local_logger=main_logger,
    )
    if not result:
        print("ERROR: Failed to create command properties")
        return -1
    assert command_properties is not None

    # Create the workers (processes) and obtain their managers
    worker_managers_list: list[worker_manager.WorkerManager] = []
    result, hb_sender_mgr = worker_manager.WorkerManager.create(
        worker_properties=heartbeat_sender_properties,
        local_logger=main_logger,
    )
    if not result or hb_sender_mgr is None:
        print("ERROR: Failed to create heartbeat sender manager")
        return -1
    worker_managers_list.append(hb_sender_mgr)

    result, hb_receiver_mgr = worker_manager.WorkerManager.create(
        worker_properties=heartbeat_receiver_properties,
        local_logger=main_logger,
    )
    if not result or hb_receiver_mgr is None:
        print("ERROR: Failed to create heartbeat receiver manager")
        return -1
    worker_managers_list.append(hb_receiver_mgr)

    result, telemetry_mgr = worker_manager.WorkerManager.create(
        worker_properties=telemetry_properties,
        local_logger=main_logger,
    )
    if not result or telemetry_mgr is None:
        print("ERROR: Failed to create telemetry manager")
        return -1
    worker_managers_list.append(telemetry_mgr)

    result, command_mgr = worker_manager.WorkerManager.create(
        worker_properties=command_properties,
        local_logger=main_logger,
    )
    if not result or command_mgr is None:
        print("ERROR: Failed to create command manager")
        return -1
    worker_managers_list.append(command_mgr)

    # Start worker processes
    for mgr in worker_managers_list:
        mgr.start_workers()

    main_logger.info("Started")

    # Main's work: read from all queues that output to main, and log any commands that we make
    # Continue running for 100 seconds or until the drone disconnects
    deadline = time.time() + MAIN_LOOP_DURATION_S
    disconnected = False
    while time.time() < deadline and not disconnected:
        try:
            state_str = heartbeat_receiver_to_main.queue.get(timeout=0.1)
            main_logger.info(state_str)
            if state_str == "Disconnected":
                disconnected = True

            cmd_str = command_to_main.queue.get(timeout=0)
            main_logger.info(cmd_str)
        except queue.Empty:
            pass

    # Stop the processes
    controller.request_exit()

    main_logger.info("Requested exit")

    # Fill and drain queues from END TO START
    command_to_main.fill_and_drain_queue()
    telemetry_to_command.fill_and_drain_queue()
    heartbeat_receiver_to_main.fill_and_drain_queue()

    main_logger.info("Queues cleared")

    # Clean up worker processes
    for mgr in worker_managers_list:
        mgr.join_workers()

    main_logger.info("Stopped")

    # We can reset controller in case we want to reuse it
    # Alternatively, create a new WorkerController instance
    controller.clear_exit()

    # =============================================================================================
    #                          ↑ BOOTCAMPERS MODIFY ABOVE THIS COMMENT ↑
    # =============================================================================================

    return 0


if __name__ == "__main__":
    result_main = main()
    if result_main < 0:
        print(f"Failed with return code {result_main}")
    else:
        print("Success!")
