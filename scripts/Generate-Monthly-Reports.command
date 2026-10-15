#!/bin/bash
# officework - Monthly Report One-Click Shortcut

CURRENT_YEAR=$(date +%Y)
CURRENT_MONTH=$(date +%m)
CURRENT_MONTH_NUM=$((10#$CURRENT_MONTH))

echo "=================================================="
echo " officework - Monthly Salary & Attendance Bundle  "
echo "=================================================="
echo "Target Server: http://100.123.152.121:1212"
echo ""

read -p "Enter Year [$CURRENT_YEAR]: " INPUT_YEAR
YEAR=${INPUT_YEAR:-$CURRENT_YEAR}

read -p "Enter Month (1-12) [$CURRENT_MONTH_NUM]: " INPUT_MONTH
MONTH=${INPUT_MONTH:-$CURRENT_MONTH_NUM}

DEST_DIR="$HOME/Downloads/Salary_Reports_${YEAR}_${MONTH}"
mkdir -p "$DEST_DIR"
ZIP_FILE="$DEST_DIR/Salary_Package_${YEAR}_${MONTH}.zip"

echo ""
echo "Downloading monthly package from sk server..."
curl -s -f "http://100.123.152.121:1212/api/export/all-zip?year=${YEAR}&month=${MONTH}" -o "$ZIP_FILE"

if [ $? -eq 0 ] && [ -s "$ZIP_FILE" ]; then
    echo "✓ Package downloaded successfully!"
    echo "Extracting files..."
    unzip -q -o "$ZIP_FILE" -d "$DEST_DIR"
    rm -f "$ZIP_FILE"
    echo "✓ All PDFs and Excel files ready in: $DEST_DIR"
    open "$DEST_DIR"
else
    echo "❌ Failed to download package. Please check if sk server is running on port 1212."
fi

echo ""
read -p "Press Enter to close..."
