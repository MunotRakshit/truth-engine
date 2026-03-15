# QuantumFlow Engine - Installation Guide

**Wiki Version:** 1.8.3
**Last Updated:** 2024-02-10
**Author:** DevOps Team
**Status:** ACTIVE (Note: Some sections may be outdated. Refer to official manual for latest procedures.)

---

## Overview

This guide covers the installation and initial setup of the QuantumFlow Engine (QFE). It is intended for system administrators and data center technicians performing first-time installations.

The QuantumFlow Engine is a high-performance data processing system capable of real-time analytics and stream processing. It uses quantum-inspired parallel processing to deliver sub-millisecond latency for data transformations.

---

## Prerequisites

Before starting the installation, ensure you have:

- Rack space: 4U for QFE-100/200, 8U for QFE-300
- Power: 200-240V AC, 50/60 Hz circuits provisioned
- Network: 10GbE cabling for data, 1GbE for management
- Tools: Torque wrench, anti-static wrist strap
- Personnel: Certified QFE installation technician

### Environmental Requirements

- Temperature: 18-24°C (64-75°F)
- Humidity: 40-60% RH (non-condensing)
- Altitude: Below 3000m

---

## Step 1: Physical Installation

### Rack Mounting

1. Install the rail kit using the provided cage nuts and mounting screws. Tighten to 3.5 Nm.
2. Slide the QFE chassis onto the rails until it clicks into the locked position.
3. Secure the chassis with front mounting bolts. **Tighten to 45 Nm** using a calibrated torque wrench.

> **Warning:** Over-torquing (>50 Nm) may crack the chassis mounting points. Under-torquing (<40 Nm) may cause vibration damage.

### Cable Connections

4. Connect redundant power cables to both PSUs. Verify both PSU LEDs are green.
5. Connect data network cables to at least two SFP+ ports.
6. Connect the management network cable.
7. Connect the serial console cable for initial setup.

---

## Step 2: Power-On and Warmup

### Initial Power-On

1. Turn on the main power switch (rear panel). The POWER LED will go green.
2. Wait for POST (Power-On Self-Test) to complete — approximately 90 seconds. STATUS LED blinks amber during POST.

### Warmup Phase

3. After POST, the warmup phase begins automatically. STATUS LED turns solid amber.

4. **The warmup phase takes approximately 5 MINUTES.** During warmup, the QPUs gradually increase to the operating temperature of **65°C**. Do not send data to the system during warmup.

   > **Note:** The warmup duration may vary slightly depending on ambient temperature. In colder environments, warmup may take up to 7 minutes.

5. When warmup completes, the STATUS LED turns solid green. The console displays: "QUANTUMFLOW ENGINE READY"

6. Verify the operating temperature:
   ```
   $ qfctl diagnostics --thermal
   ```
   Expected: QPU Thermal Status: NOMINAL (65.0°C +/- 2.0°C)

---

## Step 3: Calibration

After warmup, perform the calibration procedure to ensure optimal processing accuracy.

### Two-Step Calibration Process

The QuantumFlow Engine uses a two-step calibration process:

#### Calibration Step 1: Memory Subsystem

```
$ qfctl calibrate --subsystem memory
```

- Duration: 3-5 minutes
- Calibrates memory timings across all DIMMs
- Success: "Memory calibration PASSED"

#### Calibration Step 2: Processing Cores

```
$ qfctl calibrate --subsystem cores
```

- Duration: 5-8 minutes
- Tests all QPU execution lanes and verifies clock stability
- QPU temps may spike to 78°C briefly — this is normal
- Success: "Core calibration PASSED"

### Verification

After both calibration steps, run the verification:

```
$ qfctl calibrate --verify-all
```

Expected output:
```
Full system calibration VERIFIED
Memory: PASS
Cores: PASS
System is ready for production workloads.
```

> **Tip:** If calibration fails, check the error code and consult the troubleshooting wiki page.

---

## Step 4: Network Configuration

Configure the management and data network interfaces:

### Management Network
```
$ qfctl network set-mgmt --ip 10.0.1.100 --mask 255.255.255.0 --gw 10.0.1.1
```

### Data Network
```
$ qfctl network set-data --port 1 --ip 10.1.0.100 --mask 255.255.255.0
$ qfctl network set-data --port 2 --ip 10.1.0.101 --mask 255.255.255.0
```

### Cluster Setup (Multi-Node Only)
```
$ qfctl cluster init --cluster-name prod-cluster --node-id 1
```

### Verify Connectivity
```
$ qfctl network test --all
```

---

## Step 5: License Activation

1. Get your hardware ID:
   ```
   $ qfctl license show-hwid
   ```

2. Go to the licensing portal and submit your hardware ID.

3. Download and apply the license:
   ```
   $ qfctl license apply --file /path/to/license.qfl
   ```

4. Verify:
   ```
   $ qfctl license verify
   ```

---

## Step 6: Initial Configuration

Apply the recommended initial configuration. See the [Configuration Guide](configuration.md) for detailed parameter descriptions.

### Quick Start Configuration

Edit `/etc/quantumflow/qfengine.conf`:

```ini
# Processing
max_threads = 8
buffer_size = 2048KB
timeout = 30s
compression = LZ4

# Network
listen_address = 0.0.0.0
api_port = 8080
data_port = 9090
tls_enabled = true

# Storage
data_dir = /var/lib/quantumflow/data
log_dir = /var/log/quantumflow
log_level = INFO

# Monitoring
metrics_enabled = true
metrics_port = 9100
```

> **Note:** These are conservative default settings suitable for initial testing. Adjust based on your workload after benchmarking.

---

## Step 7: Start the Service

```
$ qfctl service start
```

Monitor startup:
```
$ qfctl service status
```

The system should show all processing threads active and ready to accept jobs within 30 seconds.

---

## Post-Installation Checklist

- [ ] Physical installation secure (45 Nm torque verified)
- [ ] Both PSUs connected and showing green LEDs
- [ ] Network cables connected (minimum 2 data ports + 1 management)
- [ ] Warmup completed successfully (5 minutes, 65°C)
- [ ] Calibration passed (both steps)
- [ ] Network configured and tested
- [ ] License applied and verified
- [ ] Configuration applied
- [ ] Service started and operational
- [ ] Baseline benchmark run for future comparison

---

## Common Installation Issues

### Warmup Takes Too Long

If warmup takes more than 7 minutes:
- Check ambient temperature (should be 18-24°C)
- Verify all fans are operational: `$ qfctl diagnostics --fans`
- If ambient temperature is below 18°C, warmup may take longer — this is normal

### Calibration Fails

If calibration fails on any step:
- Note the specific error code from the output
- Check the [Troubleshooting Guide](troubleshooting.md)
- Common cause: Loose cable connections — reseat all cables and retry

### Service Won't Start

If `qfctl service start` fails:
- Verify calibration was completed successfully
- Check license status: `$ qfctl license verify`
- Review logs: `$ qfctl logs --tail 50`

---

## Revision History

| Version | Date       | Author          | Changes                              |
|---------|------------|-----------------|--------------------------------------|
| 1.0     | 2023-02-01 | DevOps Team     | Initial guide                        |
| 1.5     | 2023-08-15 | DevOps Team     | Added QFE-200/300 notes              |
| 1.7     | 2024-01-10 | DevOps Team     | Updated network configuration steps  |
| 1.8     | 2024-02-01 | DevOps Team     | Added troubleshooting section         |
| 1.8.3   | 2024-02-10 | DevOps Team     | Minor corrections                    |

---

*This wiki page is maintained by the DevOps team. For official procedures, always refer to the latest Technical Manual.*
