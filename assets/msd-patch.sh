#!/bin/bash
# ============================================================
#  MSD Setup
# For: Libre Potato (AML-S905X-CC) / Ubuntu 22.04 / kvmd 3.198
# ============================================================

set -e

# --- Config ---
IMG_PATH="/root/disk.img"
MSD_MOUNT="/var/lib/kvmd/msd"

# --- Ask for image size ---
echo ""
echo "How large should the MSD disk image be?"
echo "  1) 4GB"
echo "  2) 8GB  (recommended)"
echo "  3) 16GB"
echo "  4) 32GB"
echo "  5) Custom (enter manually)"
echo ""
read -rp "Enter choice [1-5]: " SIZE_CHOICE

case "$SIZE_CHOICE" in
    1) IMG_SIZE_MB=4096 ;;
    2) IMG_SIZE_MB=8192 ;;
    3) IMG_SIZE_MB=16384 ;;
    4) IMG_SIZE_MB=32768 ;;
    5)
        read -rp "Enter size in GB: " CUSTOM_GB
        IMG_SIZE_MB=$(( CUSTOM_GB * 1024 ))
        ;;
    *) echo "Invalid choice, defaulting to 8GB."; IMG_SIZE_MB=8192 ;;
esac

echo "Image size set to $((IMG_SIZE_MB / 1024))GB (${IMG_SIZE_MB}MB)."
OVERRIDE_YAML="/etc/kvmd/override.yaml"
FSTAB="/etc/fstab"

# --- Colors ---
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# --- Must run as root ---
if [ "$EUID" -ne 0 ]; then
    error "Please run as root: sudo ./setup-msd.sh"
fi

# ============================================================
# STEP 1: Run msd-patch.sh if not already patched
# ============================================================
info "Step 1: Checking if msd-patch has been applied..."

if [ -f "/usr/lib/kvmd/msd-patch.sh" ] || [ -f "./msd-patch.sh" ]; then
    PATCH_SCRIPT="./msd-patch.sh"
    [ ! -f "$PATCH_SCRIPT" ] && PATCH_SCRIPT="/usr/lib/kvmd/msd-patch.sh"

    # Check if already patched by looking for mass_storage in kvmd-otg
    if grep -q "mass_storage" /usr/bin/kvmd-otg 2>/dev/null || \
       grep -q "mass_storage" /usr/lib/kvmd/otg.py 2>/dev/null; then
        info "MSD patch already applied, skipping."
    else
        info "Applying MSD patch..."
        bash "$PATCH_SCRIPT" || warn "Patch script returned non-zero, may already be applied."
    fi
else
    warn "msd-patch.sh not found. Skipping patch step."
    warn "If MSD doesn't work, clone fruity-pikvm and run msd-patch.sh manually."
fi

# ============================================================
# STEP 2: Create MSD mount point
# ============================================================
info "Step 2: Creating MSD mount point at $MSD_MOUNT..."
mkdir -p "$MSD_MOUNT"

# ============================================================
# STEP 3: Create disk image file
# ============================================================
info "Step 3: Checking for disk image at $IMG_PATH..."

if [ -f "$IMG_PATH" ]; then
    warn "Disk image already exists at $IMG_PATH, skipping creation."
else
    info "Creating ${IMG_SIZE_MB}MB disk image (this may take a while)..."
    dd if=/dev/zero of="$IMG_PATH" bs=1M count="$IMG_SIZE_MB" status=progress
    info "Formatting image as ext4..."
    mkfs.ext4 "$IMG_PATH"
    info "Disk image created and formatted."
fi

# ============================================================
# STEP 4: Fix /etc/fstab
# ============================================================
info "Step 4: Updating /etc/fstab..."

# Remove any existing broken kvmd msd lines
sed -i '/kvmd\/msd/d' "$FSTAB"

# Add correct entry
FSTAB_LINE="$IMG_PATH $MSD_MOUNT ext4 nodev,nosuid,noexec,rw,errors=remount-ro,data=journal,X-kvmd.otgmsd-root=$MSD_MOUNT,X-kvmd.otgmsd-user=kvmd 0 0"
echo "$FSTAB_LINE" >> "$FSTAB"
info "fstab updated."

# ============================================================
# STEP 5: Fix override.yaml
# ============================================================
info "Step 5: Updating $OVERRIDE_YAML..."

if [ ! -f "$OVERRIDE_YAML" ]; then
    cat > "$OVERRIDE_YAML" <<EOF
kvmd:
    msd:
        type: otg
EOF
    info "Created override.yaml with msd: type: otg"
else
    # If 'msd:' section exists, fix it; otherwise append
    if grep -q "type: disabled" "$OVERRIDE_YAML"; then
        sed -i 's/type: disabled/type: otg/' "$OVERRIDE_YAML"
        info "Changed msd type from disabled to otg."
    elif grep -q "type: otg" "$OVERRIDE_YAML"; then
        info "override.yaml already has msd: type: otg, skipping."
    else
        # Append msd block if not present
        cat >> "$OVERRIDE_YAML" <<EOF

kvmd:
    msd:
        type: otg
EOF
        info "Appended msd: type: otg to override.yaml."
    fi
fi

# ============================================================
# STEP 6: Mount the image now (without rebooting)
# ============================================================
info "Step 6: Mounting disk image..."
mount "$MSD_MOUNT" 2>/dev/null || mount -a 2>/dev/null || warn "Mount may have failed, a reboot should fix it."

# ============================================================
# STEP 7: Verify
# ============================================================
info "Step 7: Verifying setup..."

echo ""
echo "--- /etc/fstab (msd line) ---"
grep "kvmd" "$FSTAB" || warn "No kvmd line found in fstab!"

echo ""
echo "--- override.yaml ---"
cat "$OVERRIDE_YAML"

echo ""
echo "--- Mount check ---"
if mountpoint -q "$MSD_MOUNT"; then
    info "$MSD_MOUNT is mounted."
    df -h "$MSD_MOUNT"
else
    warn "$MSD_MOUNT is NOT mounted yet. Reboot to apply."
fi

echo ""
echo "--- USB gadget functions ---"
ls /sys/kernel/config/usb_gadget/kvmd/functions/ 2>/dev/null || warn "kvmd gadget not found yet."

# ============================================================
# Done
# ============================================================
echo ""
info "Setup complete! Rebooting in 5 seconds..."
info "After reboot, check the web UI for the Drive menu."
echo "(Press Ctrl+C to cancel reboot)"
sleep 5
reboot
