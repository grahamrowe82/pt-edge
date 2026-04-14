#!/bin/sh
set -e

SITE_DIR="domains/cyber/site"
GEN="python domains/cyber/scripts/generate_site.py --output-dir $SITE_DIR"

echo "Generating CyberEdge static site (chunked)..."

# CVE detail pages by year (~24-40K per chunk)
$GEN --chunk cve:2026
$GEN --chunk cve:2025
$GEN --chunk cve:2024
$GEN --chunk cve:2023
$GEN --chunk cve:2022
$GEN --chunk cve:2021
$GEN --chunk cve:2020
$GEN --chunk cve:2019
$GEN --chunk cve:2018
$GEN --chunk cve:pre2018

# Entity type chunks
$GEN --chunk product
$GEN --chunk vendor
$GEN --chunk weakness
$GEN --chunk pattern
$GEN --chunk technique

# Structural pages
$GEN --chunk relationships
$GEN --chunk insights

# Homepage, index pages, trending, about, SEO (last — reads all MVs for counts)
$GEN --chunk homepage

echo "Site generation complete."

exec uvicorn domains.cyber.app.main:app --host 0.0.0.0 --port 8000 --workers 2
