#!/usr/bin/env bash
# PARISCV v2 environment setup.
#
# Clones OpenHW's cv32e40x, cv32e40p (reference only), and core-v-verif at the
# commits this project was developed against, then applies our patch fixing a
# real bug found in core-v-verif's lightweight "core" testbench: it never
# connected data_wdata_o/data_rdata_i between cv32e40x_core and memory, so
# every store/load silently carried 0x0. See patches/ for details.
set -euo pipefail

CV32E40X_COMMIT=d952cd63bc1b4eb58cd893c28ef8283c781e345e
CV32E40P_COMMIT=6033d2b1be3295ec774d17ac4cf226faacfdeb08
COREVVERIF_COMMIT=f3b1f971e0e6b94deae46d279cc50ca390785369

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$ROOT/cores"
cd "$ROOT/cores"

clone_at() {
    local url=$1 dir=$2 commit=$3
    if [ -d "$dir" ]; then
        echo "-- $dir already exists, skipping clone"
        return
    fi
    git clone "$url" "$dir"
    (cd "$dir" && git checkout "$commit")
}

clone_at https://github.com/openhwgroup/cv32e40x.git      cv32e40x      "$CV32E40X_COMMIT"
clone_at https://github.com/openhwgroup/cv32e40p.git      cv32e40p      "$CV32E40P_COMMIT"
clone_at https://github.com/openhwgroup/core-v-verif.git  core-v-verif  "$COREVVERIF_COMMIT"

echo "-- applying wdata/rdata + print/exit address patch to core-v-verif"
git -C core-v-verif apply --check "$ROOT/patches/core-v-verif-cv32e40x-wdata-rdata-fix.patch" 2>/dev/null \
    && git -C core-v-verif apply "$ROOT/patches/core-v-verif-cv32e40x-wdata-rdata-fix.patch" \
    || echo "   (patch already applied or does not apply cleanly -- check manually)"

echo "-- copying our test programs into core-v-verif's custom test tree"
mkdir -p core-v-verif/cv32e40x/tests/programs/custom
cp -r "$ROOT/rtl-tests/pg_minimal" core-v-verif/cv32e40x/tests/programs/custom/
cp -r "$ROOT/rtl-tests/pg_matmult" core-v-verif/cv32e40x/tests/programs/custom/

echo "-- done. See README.md for how to run the CV32E40X Verilator flow and Spike ISS."
