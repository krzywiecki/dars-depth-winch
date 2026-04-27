#!/usr/bin/env python3
"""
Bi-Directional Winch Motor Controller
Receives UDP signals from the controller and controls motor speed and direction.
L2 trigger: Counter-clockwise rotation (0-255 → 0%-25% power)
R2 trigger: Clockwise rotation (0-255 → 0%-25% power)
"""

import socket
import sys
import signal
from datetime import datetime
import RPi.GPIO as GPIO
import time

# Configuration
UDP_PORT = 5008
UDP_IP = "0.0.0.0"  # Listen on all interfaces

# Motor Configuration
PWM_PIN = 18                  # PWM signal pin
CLOCKWISE_PIN = 19            # Pin 5 on controller (clockwise direction)
COUNTER_CLOCKWISE_PIN = 20    # Pin 6 on controller (counter-clockwise direction)
FREQUENCY = 1000              # Fixed frequency at 1kHz
MAX_POWER = 25                # Maximum 25% duty cycle
MIN_MOTOR_POWER = 0           # Minimum 0% duty cycle

class WinchController:
    def __init__(self):
        self.sock = None
        self.running = True
        self.pwm = None
        self.current_motor_speed = 0
        self.current_direction = "STOP"
        self.setup_motor()
        
    def setup_motor(self):
        """Initialize motor GPIO and PWM"""
        try:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            
            # Setup PWM pin
            GPIO.setup(PWM_PIN, GPIO.OUT)
            self.pwm = GPIO.PWM(PWM_PIN, FREQUENCY)
            self.pwm.start(0)  # Start with motor off
            
            # Setup direction control pins
            GPIO.setup(CLOCKWISE_PIN, GPIO.OUT)
            GPIO.setup(COUNTER_CLOCKWISE_PIN, GPIO.OUT)
            
            # Initialize to stopped state (both pins LOW = motor brake)
            self.set_direction("STOP")
            
            print(f"🔧 Motor initialized:")
            print(f"   PWM: GPIO{PWM_PIN} @ {FREQUENCY}Hz")
            print(f"   Clockwise: GPIO{CLOCKWISE_PIN}")
            print(f"   Counter-CW: GPIO{COUNTER_CLOCKWISE_PIN}")
            
        except Exception as e:
            print(f"❌ Failed to setup motor: {e}")
            sys.exit(1)
        
    def setup_socket(self):
        """Initialize UDP socket"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind((UDP_IP, UDP_PORT))
            print(f"✅ UDP server listening on {UDP_IP}:{UDP_PORT}")
            print("🎮 Waiting for controller signals...")
            print(f"🔄 L2 trigger: Counter-clockwise (0-255 → 0%-{MAX_POWER}% power)")
            print(f"🔃 R2 trigger: Clockwise (0-255 → 0%-{MAX_POWER}% power)")
            print("-" * 60)
            return True
        except Exception as e:
            print(f"❌ Failed to setup socket: {e}")
            return False
    
    def set_direction(self, direction):
        """Set motor direction by controlling GPIO pins"""
        try:
            if direction == "CLOCKWISE":
                GPIO.output(CLOCKWISE_PIN, GPIO.LOW)           # Pin 5 to GND
                GPIO.output(COUNTER_CLOCKWISE_PIN, GPIO.HIGH)  # Pin 6 to HIGH
            elif direction == "COUNTER_CLOCKWISE":
                GPIO.output(CLOCKWISE_PIN, GPIO.HIGH)          # Pin 5 to HIGH  
                GPIO.output(COUNTER_CLOCKWISE_PIN, GPIO.LOW)   # Pin 6 to GND
            else:  # STOP
                GPIO.output(CLOCKWISE_PIN, GPIO.LOW)          # Both pins GND
                GPIO.output(COUNTER_CLOCKWISE_PIN, GPIO.LOW)  # = motor brake
                
            self.current_direction = direction
            
        except Exception as e:
            print(f"⚠️ Direction control error: {e}")
    
    def calculate_motor_speed(self, trigger_value):
        """Convert trigger value (0-255) to motor speed (0-MAX_POWER%)"""
        if trigger_value <= 0:
            return 0
        
        # Map trigger value (0-255) to motor speed (0-MAX_POWER%)
        motor_speed = (trigger_value / 255.0) * MAX_POWER
        return round(motor_speed, 1)
    
    def set_motor_speed(self, speed_percent):
        """Set motor PWM speed as percentage (0-MAX_POWER%)"""
        try:
            # Clamp speed to safe range
            speed_percent = max(0, min(speed_percent, MAX_POWER))
            
            if self.pwm:
                self.pwm.ChangeDutyCycle(speed_percent)
                self.current_motor_speed = speed_percent
                
        except Exception as e:
            print(f"⚠️ Motor control error: {e}")
    
    def format_trigger_value(self, value):
        """Format trigger values with visual indication"""
        if value == 0:
            return "  0"
        elif value < 50:
            return f" {value:2d}"
        elif value < 150:
            return f"{value:3d}"
        else:
            return f">{value:2d}<"  # High values get brackets
    
    def parse_message(self, data):
        """Parse incoming UDP message"""
        try:
            message = data.decode('utf-8').strip()
            
            # Handle PING messages
            if message == "PING":
                return None
                
            # Parse TRIGGERS message
            if message.startswith("TRIGGERS,"):
                parts = message.split(",")
                if len(parts) >= 3:
                    l2_value = int(parts[1])  # 0-255
                    r2_value = int(parts[2])  # 0-255 
                    
                    return {
                        'l2': l2_value,
                        'r2': r2_value
                    }
            
            return None
        except Exception as e:
            print(f"⚠️ Parse error: {e}")
            return None
    
    def process_buttons(self, buttons):
        """Process button inputs and control motor direction and speed"""
        # Determine direction and speed based on L2/R2 triggers
        l2_speed = self.calculate_motor_speed(buttons['l2'])
        r2_speed = self.calculate_motor_speed(buttons['r2'])
        
        # Priority logic: R2 (clockwise) takes precedence if both are pressed
        if r2_speed > 0:
            self.set_direction("CLOCKWISE")
            self.set_motor_speed(r2_speed)
            active_speed = r2_speed
            active_trigger = "R2"
        elif l2_speed > 0:
            self.set_direction("COUNTER_CLOCKWISE")
            self.set_motor_speed(l2_speed)
            active_speed = l2_speed
            active_trigger = "L2"
        else:
            self.set_direction("STOP")
            self.set_motor_speed(0)
            active_speed = 0
            active_trigger = "NONE"
        
        # Display current state
        self.display_status(buttons, active_speed, active_trigger)
    
    def display_status(self, buttons, motor_speed, active_trigger):
        """Display button values and motor status"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        # Format trigger displays
        l2_display = f"L2:{self.format_trigger_value(buttons['l2'])}"
        r2_display = f"R2:{self.format_trigger_value(buttons['r2'])}"
        
        # Highlight active trigger
        if active_trigger == "L2" and buttons['l2'] > 0:
            l2_display = f"🔄 {l2_display}"  # Counter-clockwise indicator
        elif active_trigger == "R2" and buttons['r2'] > 0:
            r2_display = f"🔃 {r2_display}"  # Clockwise indicator
        
        # Motor status display with direction
        if motor_speed > 0:
            direction_symbol = "🔃" if self.current_direction == "CLOCKWISE" else "🔄"
            direction_name = "CW" if self.current_direction == "CLOCKWISE" else "CCW"
            motor_display = f"{direction_symbol} MOTOR:{motor_speed:5.1f}% {direction_name}"
        else:
            motor_display = f"⚫ MOTOR: STOPPED"
            
        print(f"[{timestamp}] {l2_display} | {r2_display} | {motor_display}")
    
    def signal_handler(self, signum, frame):
        """Handle Ctrl+C gracefully"""
        print(f"\n\n👋 Received signal {signum}, shutting down...")
        self.running = False
        self.cleanup()
        sys.exit(0)
    
    def cleanup(self):
        """Clean up resources"""
        # Stop motor
        self.set_direction("STOP")
        if self.pwm:
            self.pwm.ChangeDutyCycle(0)
            self.pwm.stop()
            print("🔧 Motor stopped")
            
        # Clean up GPIO
        GPIO.cleanup()
        print("🔧 GPIO cleaned up")
        
        # Close socket
        if self.sock:
            self.sock.close()
            print("🔌 Socket closed")
    
    def run(self):
        """Main listening loop"""
        # Setup signal handler for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        if not self.setup_socket():
            return
        
        try:
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(1024)
                    buttons = self.parse_message(data)
                    
                    if buttons:
                        self.process_buttons(buttons)
                        
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"⚠️ Receive error: {e}")
                    
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()
            print("Goodbye!")

def main():
    print("🎮 DARS Bi-Directional Winch Motor Controller")
    print("=" * 55)
    print(f"🔄 Counter-CW: L2 Trigger → 0%-{MAX_POWER}% Motor Speed")
    print(f"🔃 Clockwise:  R2 Trigger → 0%-{MAX_POWER}% Motor Speed")
    print(f"🔧 Pins: PWM=GPIO{PWM_PIN}, CW=GPIO{CLOCKWISE_PIN}, CCW=GPIO{COUNTER_CLOCKWISE_PIN}")
    print("=" * 55)
    
    controller = WinchController()
    controller.run()

if __name__ == "__main__":
    main()
