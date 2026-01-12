#
# OscilloscopeReader class for reading data from oscilloscopes via VISA
#

import pyvisa as visa
import numpy as np


class OscilloscopeReader:
    """
    A class to read data from oscilloscopes using PyVISA.
    """

    def __init__(self, device_name=None, timeout=10000):
        """
        Initialize the OscilloscopeReader.

        Args:
            device_name (str, optional): VISA resource name. If None, auto-detects first available device.
            timeout (int): Communication timeout in milliseconds (default: 10000)
        """
        self.device_name = device_name
        self.timeout = timeout
        self.rm = None
        self.device = None
        self.sample_rate = None
        self.is_connected = False

    def connect(self):
        """
        Connect to the oscilloscope device.

        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            # Initialize resource manager
            self.rm = visa.ResourceManager()

            # Get available devices
            devices = self.rm.list_resources()
            print(f"Available devices: {devices}")

            # Select device
            if self.device_name is None:
                if len(devices) == 0:
                    raise RuntimeError("No VISA devices found")
                if len(devices) > 1:
                    print(
                        f"Warning: Multiple devices found. Using first device: {devices[0]}"
                    )
                self.device_name = devices[0]
            elif self.device_name not in devices:
                raise RuntimeError(
                    f"Device '{self.device_name}' not found in available devices: {devices}"
                )

            # Open device
            self.device = self.rm.open_resource(self.device_name)
            self.device.timeout = self.timeout

            # Get device identification
            idn = self.device.query("*IDN?")
            print(f"Device Identification Number: {idn}")

            # Clear event register
            self.device.write("*CLS")

            self.is_connected = True
            return True

        except Exception as e:
            print(f"Error connecting to oscilloscope: {e}")
            if self.device:
                try:
                    self.device.close()
                except:
                    pass
            self.device = None
            self.is_connected = False
            return False

    def disconnect(self):
        """
        Close the connection to the oscilloscope.
        """
        if self.device and self.is_connected:
            try:
                self.device.close()
                self.is_connected = False
                print("Disconnected from oscilloscope")
            except Exception as e:
                print(f"Error disconnecting: {e}")

    def configure(
        self,
        memory_depth=12000,
        waveform_mode="NORM",
        waveform_format="WORD",
        time_mode="ROLL",
        start_acquisition=True,
    ):
        """
        Configure the oscilloscope settings.

        Args:
            memory_depth (int): Memory depth for the sample (default: 12000)
            waveform_mode (str): Waveform mode - "NORM", "MAX", "AVER", etc. (default: "NORM")
            waveform_format (str): Data transmission type - "WORD", "BYTE", "ASC" (default: "WORD")
            time_mode (str): Time mode - "ROLL", "MAIN", etc. (default: "ROLL")
            start_acquisition (bool): Whether to start acquisition (default: True)
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        if start_acquisition:
            self.device.write("RUN")  # Start reading

        self.device.write(f"ACQ:MDEP {memory_depth}")  # Memory depth
        self.device.write(f"WAV:MODE {waveform_mode}")  # Waveform mode
        self.device.write(f"WAV:FORM {waveform_format}")  # Data format
        self.device.write(f"TIM:MODE {time_mode}")  # Time mode

        # Get and store sample rate
        self.sample_rate = float(self.device.query("ACQ:SRAT?"))
        print(f"Sample Rate: {self.sample_rate}")

    def get_sample_rate(self):
        """
        Get the current sample rate.

        Returns:
            float: Sample rate in samples per second
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        self.sample_rate = float(self.device.query("ACQ:SRAT?"))
        return self.sample_rate

    def start_acquisition(self):
        """
        Start the oscilloscope acquisition.
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        self.device.write("RUN")

    def stop_acquisition(self):
        """
        Stop the oscilloscope acquisition.
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        self.device.write("STOP")

    def beep(self):
        """
        Make the oscilloscope beep (useful for testing connection).
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        self.device.write("SYST:BEEP ON")
        self.device.write("SYST:BEEP OFF")

    def read_values(self, channel=None):
        """
        Read the most recent waveform values from the oscilloscope.

        Args:
            channel (int, optional): Channel number to read from. If None, reads default channel.

        Returns:
            numpy.ndarray: Array of shape (2, N) where:
                - First row (index 0): X values (time/sample indices)
                - Second row (index 1): Y values (voltage/amplitude)
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        # Select channel if specified
        if channel is not None:
            self.device.write(f"WAV:SOUR CHAN{channel}")

        # Query waveform data
        y = self.device.query_binary_values(
            "WAV:DATA?", container=np.array, datatype="i"
        )

        # Generate x values (sample indices)
        x = np.arange(0, len(y))

        # Return as 2D array: [x, y]
        return np.array([x, y])

    def read_values_with_time(self, channel=None):
        """
        Read waveform values with actual time values based on sample rate.

        Args:
            channel (int, optional): Channel number to read from. If None, reads default channel.

        Returns:
            numpy.ndarray: Array of shape (2, N) where:
                - First row (index 0): Time values in seconds
                - Second row (index 1): Y values (voltage/amplitude)
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        # Get sample rate if not already stored
        if self.sample_rate is None:
            self.sample_rate = self.get_sample_rate()

        # Read values
        x, y = self.read_values(channel)

        # Convert sample indices to time
        time_values = x / self.sample_rate

        return np.array([time_values, y])

    def query(self, command):
        """
        Send a query command to the oscilloscope.

        Args:
            command (str): SCPI command string

        Returns:
            str: Response from the device
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        return self.device.query(command)

    def write(self, command):
        """
        Send a write command to the oscilloscope.

        Args:
            command (str): SCPI command string
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        self.device.write(command)

    def __enter__(self):
        """Context manager entry."""
        if not self.connect():
            raise RuntimeError("Failed to connect to oscilloscope")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False
