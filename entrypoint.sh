#!/bin/bash
# entrypoint.sh

LOG_PREFIX="[entrypoint]"

echo "$LOG_PREFIX ========== STARTUP =========="
echo "$LOG_PREFIX Args: $@"
echo "$LOG_PREFIX CLAUDE_CODE_SSE_PORT=${CLAUDE_CODE_SSE_PORT:-<not set>}"
echo "$LOG_PREFIX ENABLE_IDE_INTEGRATION=${ENABLE_IDE_INTEGRATION:-<not set>}"
echo "$LOG_PREFIX CLAUDE_CONFIG_DIR=${CLAUDE_CONFIG_DIR:-<not set>}"
echo "$LOG_PREFIX USER=$(whoami), HOME=$HOME, PWD=$PWD"
echo "$LOG_PREFIX IDE dir contents at startup:"
ls -la ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/ide/ 2>/dev/null || echo "$LOG_PREFIX IDE dir not found"

# Forward PyCharm's WebSocket port to host via socat
if [ -n "$CLAUDE_CODE_SSE_PORT" ]; then
  echo "$LOG_PREFIX Starting socat: localhost:${CLAUDE_CODE_SSE_PORT} -> host.docker.internal:${CLAUDE_CODE_SSE_PORT}"

  socat -v TCP-LISTEN:${CLAUDE_CODE_SSE_PORT},fork,reuseaddr \
        TCP:host.docker.internal:${CLAUDE_CODE_SSE_PORT} \
        2>${CLAUDE_CONFIG_DIR:-$HOME/.claude}/socat.log &

  SOCAT_PID=$!

  # Poll briefly instead of a fixed sleep to catch fast failures reliably
  for i in 1 2 3 4 5; do
    sleep 0.1
    kill -0 $SOCAT_PID 2>/dev/null || break
  done

  if kill -0 $SOCAT_PID 2>/dev/null; then
    echo "$LOG_PREFIX socat started successfully (PID=$SOCAT_PID)"
  else
    echo "$LOG_PREFIX ERROR: socat failed to start"
  fi
else
  echo "$LOG_PREFIX Skipping socat (CLAUDE_CODE_SSE_PORT not set)"
fi

# Unique identity for this guard instance to avoid conflicts across containers
GUARD_UUID=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "$(hostname)-$$-$(date +%s%N)")

GUARD_LOG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/guard.log"
GUARD_LOG_MAX_BYTES=524288  # 512 KB

glog() {
  echo "[guard $(date '+%H:%M:%S')] $*" >> "$GUARD_LOG"
}

# Truncate guard log if it exceeds the size limit (keep last 500 lines)
truncate_guard_log() {
  if [ -f "$GUARD_LOG" ] && [ "$(wc -c < "$GUARD_LOG")" -gt "$GUARD_LOG_MAX_BYTES" ]; then
    local tmp="${GUARD_LOG}.tmp"
    tail -n 500 "$GUARD_LOG" > "$tmp" && mv "$tmp" "$GUARD_LOG"
  fi
}

glog "Guard UUID: $GUARD_UUID"

# Lock file guardian - backs up all lock files and restores them if deleted,
# but only if the IDE WebSocket port is still reachable on the host.
# Uses a heartbeat file for leader election: only one guard (across all containers)
# performs restore at a time. If the current leader goes stale (>500ms), another takes over.
(
  IDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/ide"
  BACKUP_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/ide-backups"
  HEARTBEAT_FILE="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/ide-guard-heartbeat"
  mkdir -p "$IDE_DIR" "$BACKUP_DIR"

  LOOP_COUNT=0

  while true; do
    NOW_MS=$(date +%s%3N)

    # Periodically truncate the log so it doesn't grow unbounded
    LOOP_COUNT=$(( LOOP_COUNT + 1 ))
    if [ $(( LOOP_COUNT % 300 )) -eq 0 ]; then
      truncate_guard_log
    fi

    # Leader election: skip restore if another guard has a fresh heartbeat
    if [ -f "$HEARTBEAT_FILE" ]; then
      HB_UUID=$(cut -d: -f1 "$HEARTBEAT_FILE" 2>/dev/null)
      HB_TIME=$(cut -d: -f2 "$HEARTBEAT_FILE" 2>/dev/null)
      if [ -n "$HB_UUID" ] && [ -n "$HB_TIME" ] && [ "$HB_UUID" != "$GUARD_UUID" ]; then
        AGE_MS=$(( NOW_MS - HB_TIME ))
        if [ "$AGE_MS" -lt 500 ]; then
          WAS_LEADER=0
          sleep 0.3
          continue
        fi
      fi
    fi

    # Claim leadership: write our UUID, wait a few ms for any concurrent writer
    # to also land, then read back — if we're not the last writer, back off.
    echo "${GUARD_UUID}:${NOW_MS}" > "$HEARTBEAT_FILE"
    sleep 0.05
    CURRENT_LEADER=$(cut -d: -f1 "$HEARTBEAT_FILE" 2>/dev/null)
    if [ "$CURRENT_LEADER" != "$GUARD_UUID" ]; then
      WAS_LEADER=0
      sleep 0.3
      continue
    fi

    # Log when we first become (or take over as) leader
    if [ "$WAS_LEADER" != "1" ]; then
      glog "Became leader (UUID=$GUARD_UUID)"
      WAS_LEADER=1
    fi

    # Back up any new lock files
    for f in "$IDE_DIR"/*.lock; do
      [ -f "$f" ] || continue
      fname=$(basename "$f")
      backup="$BACKUP_DIR/$fname"
      if [ ! -f "$backup" ]; then
        cp "$f" "$backup"
        glog "Backed up lock file: $fname"
      fi
    done

    # Check each backup and restore if deleted, but only if port is still alive
    ALIVE_PORTS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.alive_ports"
    for backup in "$BACKUP_DIR"/*.lock; do
      [ -f "$backup" ] || continue
      fname=$(basename "$backup")
      original="$IDE_DIR/$fname"

      LOCK_PORT="${fname%.lock}"
      if [ -n "$LOCK_PORT" ] && [ -f "$ALIVE_PORTS" ] && ! grep -qw "$LOCK_PORT" "$ALIVE_PORTS"; then
        rm "$backup"
        glog "IDE port $LOCK_PORT no longer alive, removing backup: $fname"
        continue
      fi

      # Lock file missing but PID still alive - restore it
      if [ ! -f "$original" ]; then
        cp "$backup" "$original"
        glog "Restored lock file: $fname"
      fi
    done

    sleep 0.3
  done
) &
glog "Lock file guardian started (PID=$!, UUID=$GUARD_UUID)"

echo "$LOG_PREFIX ============================="
echo "$LOG_PREFIX guard log: $GUARD_LOG"
echo "$LOG_PREFIX socat log: ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/socat.log"
echo "$LOG_PREFIX Launching: claude $@"

exec claude "$@"