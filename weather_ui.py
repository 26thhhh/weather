#!/usr/bin/env python3
import curses
import sqlite3
import textwrap
import sys
from pathlib import Path

from location import ensure_location, handle_location_command

DATABASE_PATH = Path.home() / ".local/share/kanslor-weather/history.sqlite3"


def draw_line(screen, row, text, selected=False, color=0):
    height, width = screen.getmaxyx()
    if row >= height:
        return
    try:
        screen.addnstr(row, 0, text.ljust(max(width - 1, 1)), max(width - 1, 1), curses.A_REVERSE if selected else color)
    except curses.error:
        pass


def alert_rows(connection, active_only):
    where = "WHERE active = 1" if active_only else ""
    return connection.execute(f"""
        SELECT alert_id, event, severity, urgency, sent, expires, area, headline,
               description, instruction, web, active
        FROM alerts {where}
        ORDER BY active DESC, expires DESC, sent DESC
    """).fetchall()


def latest_condition(connection):
    return connection.execute("""
        SELECT observed_at, station_id, station_name, description, temperature_f, humidity,
               wind_mph, wind_direction, wind_gust_mph, heat_index_f, visibility_miles
        FROM conditions ORDER BY observed_at DESC LIMIT 1
    """).fetchone()


def compass(degrees):
    if degrees is None:
        return "--"
    points = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    return points[round(degrees / 45) % 8]


def condition_art(description):
    text = (description or "").lower()
    if any(word in text for word in ("thunder", "storm")):
        return ("     .--.     ", "  .-(    ).   ", " (___.__)__)  ", "    / / / /    ", "      /_/       ")
    if any(word in text for word in ("rain", "shower", "drizzle")):
        return ("     .--.     ", "  .-(    ).   ", " (___.__)__)  ", "   / / / /     ")
    if any(word in text for word in ("snow", "sleet", "ice")):
        return ("     .--.     ", "  .-(    ).   ", " (___.__)__)  ", "   *  *  *     ")
    if any(word in text for word in ("cloud", "overcast", "fog", "haze")):
        return ("     .--.     ", "  .-(    ).   ", " (___.__)__)  ")
    return ("    \\   /      ", "     .-.       ", "  -- ( ) --    ", "     `-'       ", "    /   \\      ")


def draw_condition_header(screen, condition):
    if not condition:
        draw_line(screen, 2, "CURRENT CONDITIONS UNAVAILABLE")
        return 5
    observed_at, station_id, station_name, description, temperature_f, humidity, wind_speed, wind_direction, wind_gust, heat_index, visibility = condition
    temperature = f"{temperature_f:.0f}F" if temperature_f is not None else "--"
    humidity_text = f"{humidity:.0f}%" if humidity is not None else "--"
    wind_text = f"{compass(wind_direction)} {wind_speed:.0f} mph" if wind_speed is not None else "CALM/--"
    gust_text = f"{wind_gust:.0f} mph" if wind_gust is not None else "--"
    heat_text = f"{heat_index:.0f}F" if heat_index is not None else "--"
    visibility_text = f"{visibility:.1f} mi" if visibility is not None else "--"
    draw_line(screen, 2, f"NOW: {description or '--'} | {temperature} | HUMIDITY {humidity_text}")
    draw_line(screen, 3, f"WIND: {wind_text} | GUSTS {gust_text} | HEAT INDEX {heat_text} | VISIBILITY {visibility_text}")
    draw_line(screen, 4, f"OBSERVATION: {station_name or station_id or '--'} | {observed_at or '--'}", color=curses.color_pair(2))
    _, width = screen.getmaxyx()
    art = condition_art(description)
    if width >= 100:
        art_x = width - 18
        for row, line in enumerate(art, 2):
            try:
                screen.addnstr(row, art_x, line, max(width - art_x - 1, 1), curses.color_pair(1))
            except curses.error:
                pass
        return 6
    for row, line in enumerate(art, 5):
        draw_line(screen, row, line, color=curses.color_pair(1))
    return 5 + len(art)


def detail_view(screen, alert):
    scroll = 0
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        draw_line(screen, 0, f"NWS ALERT // {alert[1] or 'Unknown'}", color=curses.color_pair(1))
        draw_line(screen, 1, "UP/DOWN scroll  ESC return to alert list")
        lines = [
            f"SEVERITY: {alert[2] or '--'}   URGENCY: {alert[3] or '--'}",
            f"ISSUED: {alert[4] or '--'}",
            f"EXPIRES: {alert[5] or '--'}",
            f"AREA: {alert[6] or '--'}",
            "",
            "HEADLINE:", alert[7] or "--", "",
            "DESCRIPTION:", alert[8] or "--", "",
            "INSTRUCTIONS:", alert[9] or "No public instructions provided.",
        ]
        wrapped = []
        for line in lines:
            wrapped.extend(textwrap.wrap(line, max(width - 2, 20)) or [""])
        for index, line in enumerate(wrapped[scroll:scroll + height - 3], 3):
            draw_line(screen, index, line)
        screen.refresh()
        key = screen.getch()
        if key in (27, ord("q"), ord("Q")):
            return
        if key in (curses.KEY_DOWN, ord("j")) and scroll < max(len(wrapped) - height + 3, 0):
            scroll += 1
        if key in (curses.KEY_UP, ord("k")) and scroll > 0:
            scroll -= 1


def app(screen):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_YELLOW, -1)
    curses.init_pair(2, curses.COLOR_CYAN, -1)
    active_only = True
    selected = 0
    while True:
        screen.erase()
        if not DATABASE_PATH.exists():
            draw_line(screen, 0, "N W S  //  WEATHER ALERT WATCH", color=curses.color_pair(1))
            draw_line(screen, 2, "No alert history yet. The collector will create it on its next ten-minute run.")
            draw_line(screen, 4, "ESC exit")
            screen.refresh()
            if screen.getch() == 27:
                return
            continue
        with sqlite3.connect(DATABASE_PATH) as connection:
            rows = alert_rows(connection, active_only)
            condition = latest_condition(connection)
            mode = "ACTIVE" if active_only else "HISTORY"
            draw_line(screen, 0, f"N W S  //  WEATHER ALERT WATCH   [{mode}]", color=curses.color_pair(1))
            draw_line(screen, 1, "UP/DOWN select  ENTER detail  A active  H history  R refresh  ESC exit")
            list_start = draw_condition_header(screen, condition)
            draw_line(screen, list_start, "EVENT                              SEVERITY      URGENCY       EXPIRES", color=curses.color_pair(2))
            height, _ = screen.getmaxyx()
            visible = max(height - list_start - 2, 1)
            start = max(0, selected - visible + 1)
            for index, alert in enumerate(rows[start:start + visible], start):
                text = f"{(alert[1] or '--'):<34.34} {(alert[2] or '--'):<13.13} {(alert[3] or '--'):<13.13} {(alert[5] or '--'):<24.24}"
                draw_line(screen, index - start + list_start + 1, text, index == selected)
            if not rows:
                draw_line(screen, list_start + 2, "No matching alerts. Press H to view prior alerts after they are recorded.")
            screen.refresh()
            key = screen.getch()
            if key in (27, ord("q"), ord("Q")):
                return
            if key in (curses.KEY_DOWN, ord("j")) and selected < len(rows) - 1:
                selected += 1
            elif key in (curses.KEY_UP, ord("k")) and selected > 0:
                selected -= 1
            elif key in (10, 13, curses.KEY_ENTER) and rows:
                detail_view(screen, rows[selected])
            elif key in (ord("a"), ord("A")):
                active_only, selected = True, 0
            elif key in (ord("h"), ord("H")):
                active_only, selected = False, 0


if __name__ == "__main__":
    if not handle_location_command(sys.argv[1:]):
        ensure_location(interactive=True)
        curses.wrapper(app)
