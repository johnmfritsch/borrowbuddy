# BorrowBuddy 📚

A self-hosted web application for tracking borrowed and loaned items — books, tools, gear, anything. Built for real household use with a clean, mobile-friendly UI.

## Features

- Track items loaned out and borrowed
- Per-person loan history
- Due date tracking
- Mobile-friendly responsive UI
- REST API backend
- Self-hosted, private data

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python / Flask |
| Database | SQLite |
| Frontend | HTML / CSS / JavaScript |
| API | REST (JSON) |
| Hosting | Self-hosted on ASUSTOR NAS |
| Web Server | Nginx reverse proxy → Flask |
| SSL | Let's Encrypt (auto-renewed) |

## Architecture

Flask application running with SSL on a dedicated port, accessible externally via port forwarding:
- **External:** `https://[hostname]:7781/BorrowBuddy`
- **LAN:** `https://192.168.x.x/BorrowBuddy`

## Project Structure

```
app.py              # Main Flask application + REST API
loan.html           # Main UI template
loan_current.html   # Active loans view
duplicate-checker.js # Client-side duplicate detection
```

## Live Demo

> **[Open BorrowBuddy](https://fritsch-nas.myasustor.com:7781/BorrowBuddy)**
