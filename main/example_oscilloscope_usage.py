#
# Example usage of OscilloscopeReader class
#

from oscilloscope_reader import OscilloscopeReader
import matplotlib.pyplot as plt


def main():
    # Create oscilloscope reader instance (auto-detect device)
    reader = OscilloscopeReader()

    try:
        # Connect to the oscilloscope
        if not reader.connect():
            print("Failed to connect to oscilloscope")
            return

        # Configure the oscilloscope
        print("\n--- Configuring oscilloscope ---")
        reader.configure(
            memory_depth=12000,
            waveform_mode="NORM",
            waveform_format="WORD",
            time_mode="ROLL",
            start_acquisition=True,
        )

        # Test beep
        print("\n--- Testing connection (beep) ---")
        reader.beep()

        # Example 1: Read values (sample indices)
        print("\n--- Example 1: Reading waveform values ---")
        data = reader.read_values()
        print(f"Data shape: {data.shape}")
        print(f"Number of samples: {len(data[0])}")
        print(f"First 5 X values: {data[0][:5]}")
        print(f"First 5 Y values: {data[1][:5]}")

        # Example 2: Read values with actual time
        print("\n--- Example 2: Reading waveform with time ---")
        time_data = reader.read_values_with_time()
        print(f"Time range: {time_data[0][0]:.6f} to {time_data[0][-1]:.6f} seconds")
        print(f"Sample rate: {reader.sample_rate} samples/second")

        # Example 3: Read from specific channel
        print("\n--- Example 3: Reading from channel 1 ---")
        try:
            channel_data = reader.read_values(channel=1)
            print(f"Channel 1 data shape: {channel_data.shape}")
        except Exception as e:
            print(f"Error reading channel 1: {e}")

        # Example 4: Multiple reads
        print("\n--- Example 4: Reading multiple times ---")
        for i in range(3):
            data = reader.read_values()
            print(
                f"Read {i+1}: {len(data[0])} samples, Y range: [{data[1].min()}, {data[1].max()}]"
            )

        # Example 5: Custom query
        print("\n--- Example 5: Custom query ---")
        idn = reader.query("*IDN?")
        print(f"Device ID: {idn}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()

    finally:
        # Disconnect
        reader.disconnect()


def example_with_context_manager():
    """
    Example using the context manager (with statement).
    This automatically handles connection and disconnection.
    """
    print("\n--- Example with context manager ---")

    try:
        with OscilloscopeReader() as reader:
            # Configure
            reader.configure(memory_depth=12000)

            # Read values
            data = reader.read_values()
            print(f"Read {len(data[0])} samples")

            # Read with time
            time_data = reader.read_values_with_time()
            print(f"Time span: {time_data[0][-1] - time_data[0][0]:.6f} seconds")

    except Exception as e:
        print(f"Error: {e}")


def example_plotting():
    """
    Example of reading and plotting oscilloscope data.
    """
    print("\n--- Example: Plotting waveform ---")

    try:
        with OscilloscopeReader() as reader:
            # Configure
            reader.configure(memory_depth=12000)

            # Read data with time
            time_data = reader.read_values_with_time()

            # Plot
            plt.figure(figsize=(10, 6))
            plt.plot(time_data[0], time_data[1])
            plt.xlabel("Time (seconds)")
            plt.ylabel("Amplitude")
            plt.title("Oscilloscope Waveform")
            plt.grid(True)
            plt.show()

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    # Run main example
    main()

    # Uncomment to run context manager example
    # example_with_context_manager()

    # Uncomment to run plotting example (requires matplotlib)
    # example_plotting()
