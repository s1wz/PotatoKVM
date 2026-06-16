# PotatoKVM
A slightly modified PiKVM instance with a 3D-printed case and screen, built using a Le Potato (AML-S905X-CC) and a USB HDMI capture card.

---

## Requirements
- Le Potato (AML-S905X-CC)
- USB HDMI capture card
- MicroSD card (16GB+)
- A machine to flash the image from

---

## Installation

1. **Flash Ubuntu Server:** Download and flash the official Libre Computer Ubuntu Server image to your SD card.
   [ubuntu-22.04.3-preinstalled-server-arm64+aml-s905x-cc.img.xz](https://distro.libre.computer/ci/ubuntu/22.04/ubuntu-22.04.3-preinstalled-server-arm64%2Baml-s905x-cc.img.xz)

2. **Enable USB OTG:** Run the following so the board can act as a KVM gadget:
```bash
   sudo ldto merge usb-device-mode
```
   >  **NOTE:** If you're powering the board through a USB OTG cable, block pin 1 (VBUS) on the connector or it'll hang on boot.

3. **Install FruityKVM:** Update your packages and install it:
```bash
   sudo apt update && sudo apt upgrade -y
```
   Then follow the instructions at [fruity-pikvm](https://github.com/jacobbar/fruity-pikvm).

4. **Patch MSD:** Run the MSD patch script in this repo to get Mass Storage Device emulation working:
```bash
   sudo bash msd-patch.sh
```

5. **You now have a KVM!!**

---

## Extras
- Threw in a generic 5V AliExpress fan for cooling — works fine
- Added a simple SPI display, code's in the `assets/` folder
- 3D printed a case for it, files are in `assets/` — keep in mind it was a 30-minute job and it clearly shows, subject to change
