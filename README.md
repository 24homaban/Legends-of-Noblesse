# Legends of Noblesse (Pygame)

This submission includes:
- Full source code for the game.
- A prebuilt, single-file Windows executable: `dist/LegendsOfNoblesse.exe`.

## 1. Download The Source Code

Use one of the following:

1. Git clone (if a repository URL is provided with the submission):
   - `git clone <provided_repository_url>`
2. ZIP download:
   - Download the project ZIP from the submission/repository page.
   - Extract it to a local folder.

After extraction, open a terminal in the project root (the folder containing `main.py`).

## 2. Project Layout

- `main.py`
  - Program entrypoint (starts the Pygame application).
- `game/`
  - Core game rules and data models (phases, combat, card logic, player state).
- `ui/`
  - Pygame scenes and rendering logic.
- `adapters/`
  - Adapter layer between UI and game engine actions.
- `data/Cards/`
  - JSON card definitions used by the loader.
- `assets/`
  - Card and board art assets.
- `tests/`
  - Ability and rules simulation tests.
- `analysis/`
  - Scripts used for matchup/balance analysis.
- `reports/`
  - Generated analysis outputs.
- `dist/`
  - Built executable output (contains `LegendsOfNoblesse.exe`).

## 3. Run From Source (Recommended For Code Review)

### Requirements
- Windows (tested)
- Python 3.12+

### Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### Start The Game

```powershell
python main.py
```

## 4. Run The Prebuilt Playable Executable

A prebuilt executable is already included:

```powershell
.\dist\LegendsOfNoblesse.exe
```

Notes:
- This is a single-file executable build.
- No Python installation is required to run the executable.

## 5. Optional: Rebuild The Executable

If you want to reproduce the build:

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "LegendsOfNoblesse" --add-data "assets;assets" --add-data "data;data" main.py
```

This generates `dist/LegendsOfNoblesse.exe`.

## 6. Basic In-Game Usage

- Launch the game.
- Use the start/select screens to choose class, barracks, deck, and battlefield setup for both players.
- Continue into gameplay and progress through phases using on-screen controls.

## 7. Troubleshooting

- If Windows SmartScreen prompts on first launch of the executable, choose **More info** then **Run anyway**.
- If running from source fails with module errors, ensure the virtual environment is activated and dependencies were installed with `requirements.txt`.
