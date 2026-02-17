"""GPIO hardware backend for Raspberry Pi RC car.

Requires: RPi.GPIO (pip install RPi.GPIO)
Optional: adafruit-circuitpython-ads1x15 for battery ADC

Wiring:
    L298N motor driver: 4 GPIO pins (2 per motor)
    Servo pan/tilt: 2 PWM GPIO pins
    Trigger relay: 1 GPIO pin
    Battery ADC: I2C (SDA/SCL) + ADS1115
"""

from __future__ import annotations

import time

from .base import HardwareInterface


class GPIOHardware(HardwareInterface):
    """Real GPIO hardware control for Raspberry Pi."""

    def __init__(self, config: dict) -> None:
        hw_cfg = config.get("hardware", {})
        self._pins = {
            "mlf": hw_cfg.get("motor_left_forward", 17),
            "mlb": hw_cfg.get("motor_left_backward", 27),
            "mrf": hw_cfg.get("motor_right_forward", 22),
            "mrb": hw_cfg.get("motor_right_backward", 23),
            "turret_pan": hw_cfg.get("turret_pan_pin", 12),
            "turret_tilt": hw_cfg.get("turret_tilt_pin", 13),
            "trigger": hw_cfg.get("trigger_pin", 24),
        }
        self._battery_pin = config.get("telemetry", {}).get("battery_pin")
        self._gpio = None
        self._pwm = {}
        # Position tracking (needs IMU/GPS in real implementation)
        self._x = 0.0
        self._y = 0.0
        self._heading = 0.0
        self._speed = 0.0

    def initialize(self) -> None:
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            # Motor pins
            for pin_name in ("mlf", "mlb", "mrf", "mrb"):
                GPIO.setup(self._pins[pin_name], GPIO.OUT)
                self._pwm[pin_name] = GPIO.PWM(self._pins[pin_name], 1000)
                self._pwm[pin_name].start(0)

            # Servo pins
            for pin_name in ("turret_pan", "turret_tilt"):
                GPIO.setup(self._pins[pin_name], GPIO.OUT)
                self._pwm[pin_name] = GPIO.PWM(self._pins[pin_name], 50)
                self._pwm[pin_name].start(7.5)  # center position

            # Trigger pin
            GPIO.setup(self._pins["trigger"], GPIO.OUT)
            GPIO.output(self._pins["trigger"], GPIO.LOW)

            print("  Hardware: GPIO initialized")
            print(f"  Motor pins: LF={self._pins['mlf']} LB={self._pins['mlb']} "
                  f"RF={self._pins['mrf']} RB={self._pins['mrb']}")
        except ImportError:
            raise RuntimeError(
                "RPi.GPIO not available. Use --simulate for testing, "
                "or install RPi.GPIO on a Raspberry Pi."
            )

    def shutdown(self) -> None:
        if self._gpio is None:
            return
        self.set_motors(0, 0)
        for pwm in self._pwm.values():
            pwm.stop()
        self._gpio.cleanup()
        print("  GPIO hardware shut down")

    def set_motors(self, left: float, right: float) -> None:
        if self._gpio is None:
            return
        left = max(-1.0, min(1.0, left))
        right = max(-1.0, min(1.0, right))

        # Left motor
        if left >= 0:
            self._pwm["mlf"].ChangeDutyCycle(left * 100)
            self._pwm["mlb"].ChangeDutyCycle(0)
        else:
            self._pwm["mlf"].ChangeDutyCycle(0)
            self._pwm["mlb"].ChangeDutyCycle(abs(left) * 100)

        # Right motor
        if right >= 0:
            self._pwm["mrf"].ChangeDutyCycle(right * 100)
            self._pwm["mrb"].ChangeDutyCycle(0)
        else:
            self._pwm["mrf"].ChangeDutyCycle(0)
            self._pwm["mrb"].ChangeDutyCycle(abs(right) * 100)

    def get_position(self) -> tuple[float, float]:
        # Real implementation would use GPS, IMU, or wheel encoders
        return (self._x, self._y)

    def get_heading(self) -> float:
        # Real implementation would use magnetometer or IMU
        return self._heading

    def get_speed(self) -> float:
        return self._speed

    def get_battery(self) -> float:
        if self._battery_pin is not None:
            try:
                import board
                import busio
                import adafruit_ads1x15.ads1115 as ADS
                from adafruit_ads1x15.analog_in import AnalogIn
                i2c = busio.I2C(board.SCL, board.SDA)
                ads = ADS.ADS1115(i2c)
                chan = AnalogIn(ads, ADS.P0)
                # Assume 3S LiPo: 12.6V full, 9.6V empty
                # With voltage divider: 12.6V -> 3.3V
                voltage = chan.voltage * (12.6 / 3.3)
                return max(0.0, min(1.0, (voltage - 9.6) / (12.6 - 9.6)))
            except Exception:
                pass
        return 1.0  # Default to full if no ADC

    def set_turret(self, pan: float, tilt: float) -> None:
        if self._gpio is None:
            return
        # Convert degrees to duty cycle (2.5-12.5 for 0-180 degrees)
        pan_dc = 7.5 + (pan / 90.0) * 5.0   # -90..+90 -> 2.5..12.5
        tilt_dc = 7.5 + (tilt / 90.0) * 5.0
        pan_dc = max(2.5, min(12.5, pan_dc))
        tilt_dc = max(2.5, min(12.5, tilt_dc))
        self._pwm["turret_pan"].ChangeDutyCycle(pan_dc)
        self._pwm["turret_tilt"].ChangeDutyCycle(tilt_dc)

    def fire_trigger(self) -> None:
        if self._gpio is None:
            return
        self._gpio.output(self._pins["trigger"], self._gpio.HIGH)
        time.sleep(0.3)  # Trigger duration
        self._gpio.output(self._pins["trigger"], self._gpio.LOW)
