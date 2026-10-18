# Anki Card Adding Utility

This document outlines the system architecture, component design, and integration strategy for building a self-hosted, cloud-based Anki flashcard pipeline. The system allows users to add flashcards via a custom Rust web interface, which automatically processes data, pushes notes to a running headless Anki instance, and enforces immediate cloud synchronization.
Furhtermore the rust application after receiving a new-card defintion form the user will:
1) add audio-files to the cards (to hear to foreign language word)
2) Ask github copilot (using the github copilot SDK) for information about the origin of the word its etymology and place it on the backside of the card - described in the native language (language from frontside)
3) Apply the chosen fromatting 


All of the above are optional features that user may activate/disactivate via the browser request.


---

## 1. System Architecture Overview

The system consists of three distinct zones: the client-side user interface, the cloud-hosted processing backend, and the official Anki ecosystem.

```
[ User Browser ] 
       │ 
       │ HTTP POST (Web Form / API)
       ▼
[ Rust Web Application ] 
       │ 
       │ Localhost JSON-RPC (Port 8765)
       ▼
[ Headless Anki Desktop Instance ]  ◄─── (Running via Docker + Xvfb / AnkiConnect)
       │ 
       │ Secure HTTPS Sync Protocol
       ▼
[ AnkiWeb Cloud ] 
       │ 
       │ Sync down on demand
       ▼
[ User Mobile Device / Desktop App ]
```

---

## 2. Core Components

### A. Headless Anki Container
Because the official Anki application is fundamentally a desktop application built on Python and Qt (C++), it requires a display server to run.
* **Mechanism:** Executed inside a Linux Docker container utilizing **Xvfb** (X Virtual Framebuffer) to simulate a display headlessly.
* **API Layer:** The **AnkiConnect** add-on runs internally on port `8765`, exposing a JSON-RPC interface locally to accept commands.
* **Authentication:** Logged into AnkiWeb once (via temporary VNC/noVNC display exposure during setup) to store session tokens for subsequent syncing.

### B. Rust Application Backend & Interface
Acts as the secure, web-facing gateway for the user.
* **Web Framework:** Built using performance-oriented frameworks like **Axum** or **Actix-web**.
* **Role:** Exposes HTML forms or an API endpoint for creating cards. It formats inputs, converts media uploads to Base64 strings, and forwards requests to the headless container.
* **Security:** Acts as a reverse-proxy shield. The AnkiConnect port (`8765`) remains blocked to the outside world, bound strictly to `localhost`.

---

## 3. The 3-Step Execution Pipeline

When a user submits a card through the custom web interface, the Rust backend handles execution sequentially:

### Step 1: Ingesting Data
The user inputs text, tags, or media uploads. The Rust web server processes the request and validates the parameters.

### Step 2: Injecting the Note (AnkiConnect API)
The Rust application initiates a local HTTP `POST` request to `http://localhost:8765` invoking the `addNote` action.

```json
{
    "action": "addNote",
    "version": 6,
    "params": {
        "note": {
            "deckName": "CloudDeck",
            "modelName": "Basic",
            "fields": {
                "Front": "Rust Lang",
                "Back": "A language empowering everyone to build reliable software."
            },
            "tags": ["web_interface"]
        }
    }
}
```

### Step 3: Enforcing Online Cloud Sync
Since the cloud-based Anki instance stays open indefinitely, it will not auto-sync on close. The Rust backend immediately fires a secondary HTTP `POST` request to invoke the `sync` action:

```json
{
    "action": "sync",
    "version": 6
}
```
This pushes the newly generated card to **AnkiWeb**, making it available instantly on the user's mobile device or separate desktop clients.

---

## 4. Key Engineering Trade-offs & Operational Risks

* **Media Sync Overhead:** Processing high-resolution images or raw audio requires transforming assets into Base64 strings over JSON-RPC. To prevent blocking the user interface, media attachments should be handled asynchronously via background worker threads or queues in Rust.
* **Database Locking Conflicts:** If the user executes active card reviews on a mobile device at the exact moment the Rust system calls the `sync` action in the cloud, AnkiWeb may trigger a temporary database lock conflict.
* **Security Hardening:** AnkiConnect lacks native built-in authorization mechanisms. Network access to port `8765` must be firmly restricted via server firewalls to ensure only internal container services can issue card modifications.