# AutoPilot service manager

Navigator detection requires ADS1115 and BME280 on I2C bus 1, plus PCA9685 on
bus 4 for Pi 4 or bus 3 for Pi 5. Either AK09915 (0x0C) or IIS2MDC (0x1E) on
bus 1 must also be present.
Pi 4 boot configuration keeps Bluetooth disabled on both fresh installs and
upgraded devices.

NaviCube Pi 4 detection requires ADS1115 (0x48) on bus 1 and EEPROM (0x58) on
bus 0, plus either LIS3MDL (0x1C, V1.00) or BMM350 (0x14, V1.10) on bus 1.
Argonot retains its Pi 4 multiplexer-only detection at address 0x77 on bus 1.
