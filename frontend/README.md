# EgerBot Frontend v2
Egerton University Chatbot Interface — Full Feature Build

---

## Folder Structure

```
egerbot-frontend-v2/
├── index.html       ← Full-screen chat interface (main app)
├── widget.html      ← Floating FAB widget (embed on any page)
├── launch.bat       ← Windows double-click launcher
├── assets/
│   ├── logo.png     ← Egerton crest (white bg) — used in sidebar, bot avatar, messages
│   └── logo-green.png  ← Egerton crest (green bg) — used in header
└── README.md
```

---

## Your Question: Do I always have to type those commands?

**No — you have better options.**

### Option 1 — Double-click launch.bat (Recommended for Windows)
Just double-click `launch.bat` in File Explorer. It opens `index.html` automatically.
No PowerShell, no typing needed.

### Option 2 — VS Code Live Server (Best for development)
1. Open the project folder in VS Code
2. Install the "Live Server" extension (by Ritwick Dey)
3. Right-click `index.html` → "Open with Live Server"
4. It opens automatically at `http://127.0.0.1:5500/index.html`
5. Auto-reloads whenever you save a file — no manual refresh

### Option 3 — Pin to taskbar / Start Menu
1. Right-click `index.html` → Open with → Choose your browser
2. When it opens, bookmark it or pin the tab
3. Next time just click the bookmark

### Option 4 — Create a Desktop Shortcut (Windows)
1. Right-click `index.html`
2. Send to → Desktop (create shortcut)
3. Double-click the shortcut anytime

### Option 5 — npm serve (for production-like testing)
```bash
npm install -g serve
cd frontend
serve .
# Opens at http://localhost:3000
```

### The two PowerShell commands you showed:
```powershell
# These still work but are not necessary
start widget.html   # opens widget.html in browser
start index.html    # opens index.html in browser
```
Use these only if you specifically want to test the widget separately.
For normal development, use VS Code Live Server.

---

## Connecting to Backend

Open `index.html` and find line near top of `<script>`:
```js
const BACKEND_URL = "http://localhost:5000";
```
Change this to your deployed backend URL when ready.

---

## Features Implemented (~60 total)

### Core Chat
- [x] Chat window with scrolling message area
- [x] Input field with send button
- [x] Distinct user/bot message bubbles with notch pointers
- [x] Typing indicator with animated dots
- [x] Timestamps on all messages (toggleable)
- [x] Header with Egerton logo, bot name, online status
- [x] Message actions: Copy, Share, Report
- [x] Auto-scroll to newest message (toggleable)
- [x] Enter to send, Shift+Enter for new line, Esc to clear
- [x] Character counter with warning at 900+

### Discovery & Access
- [x] Floating Action Button widget (widget.html)
- [x] Red notification badge on FAB
- [x] Animated pulse ring on FAB
- [x] Welcome greeting message on load
- [x] EgerBot avatar with Egerton logo
- [x] Starter prompt chips (6 welcome chips)
- [x] Multi-channel indicator in settings (Web/WhatsApp/Telegram)
- [x] "Chat with EgerBot" tooltip on FAB

### User Experience
- [x] Quick reply buttons after each bot response
- [x] Mobile responsive design (sidebar collapses, full-width)
- [x] Voice input (Speech-to-Text) with mic toggle
- [x] Emoji picker with search
- [x] File attachment button (UI ready, backend extension)
- [x] Clear/Restart chat button
- [x] Expandable responses (Read more / Read less)
- [x] Inline links (URLs, emails auto-linked)
- [x] Download chat as .txt file
- [x] Announcement card for intake notices

### Personalization
- [x] User type selector: Prospective Student / Parent / Visitor
- [x] Language toggle: English / Kiswahili
- [x] Bookmarks / Saved messages with panel
- [x] Context memory within session
- [x] Topic chips for personalized navigation

### Intelligence
- [x] Language detection (English/Swahili auto-switch)
- [x] Escalation detection (bot flags when it can't answer)
- [x] Conversation history sent with every message
- [x] Fallback error messages in both languages
- [x] Knowledge base integration via backend

### Feedback
- [x] Thumbs up / Thumbs down rating toast
- [x] Report answer button
- [x] Feedback sent to backend
- [x] Context menu with Report option
- [x] Confirmation toasts after feedback

### Information Display
- [x] Source citation "Egerton University" under bot responses
- [x] "Last Updated: 2025" indicator
- [x] Announcement card (2025/2026 intake notice)
- [x] Escalated answers styled with gold left border

### Accessibility
- [x] Text size adjustment: Small / Medium / Large / X-Large
- [x] High contrast mode toggle
- [x] Keyboard navigation (Enter, Shift+Enter, Esc)
- [x] ARIA labels on all interactive elements

### Privacy & Safety
- [x] Privacy notice on welcome screen (Kenya Data Protection Act)
- [x] Anonymous session (no name collected)
- [x] External links open in new tab with rel="noopener"

### Advanced
- [x] File upload button (UI)
- [x] Voice input (Speech-to-Text)
- [x] Chat search panel (search previous messages)
- [x] Pin/Bookmark important messages with panel
- [x] Offline mode detection + banner
- [x] Right-click context menu on messages
- [x] Toast notification system
- [x] Settings panel with persistence (localStorage)
- [x] Sidebar open/close with animation
- [x] Auto-resize textarea as user types
