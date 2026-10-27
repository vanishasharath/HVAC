"""
HVAC Unit 02 Simulator - High-Side / Discharge Line Scenario
============================================================
Demonstrates multi-unit simulation with distinct sensor placement:
HVAC_TEST_02 configured with Discharge Line (High-Side) pressure transducer
and contextual fluctuating ambient humidity.
"""

import sys
from pathlib import Path

# Add backend directory to path if needed
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.simulate_sensor_data import run_live_simulation

if __name__ == "__main__":
    print("Launching Live Simulator for HVAC_TEST_02 (Discharge Line / High-Side)...")
    run_live_simulation(
        location="discharge_line",
        humidity="fluctuating",
        leak_rate="medium",
        normal_steps=3,
        leak_steps=40,
        delay=1.0,
        hvac_id="HVAC_TEST_02",
    )
