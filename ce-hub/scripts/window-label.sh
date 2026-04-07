#!/bin/bash
# window-label.sh — Return padded display name for a window in the nav bar
# Usage: window-label.sh <window_name>
# Output: 9-char padded label (cell will be "  LABEL  " = 13 chars >= 14 with separator)

WINDOW="${1:-?}"

case "$WINDOW" in
  cc-lead)              echo "cc-lead  " ;;
  coder)                echo "coder    " ;;
  researcher)           echo "research " ;;
  architect)            echo "arch     " ;;
  pipeline-runner)      echo "pipeline " ;;
  code-reviewer)        echo "reviewer " ;;
  ops)                  echo "ops      " ;;
  open-data-collector)  echo "datacol  " ;;
  wiki-curator)         echo "wiki-cur " ;;
  *)                    printf "%-9s" "$WINDOW" ;;
esac
