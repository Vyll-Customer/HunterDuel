# HUNTER DUEL: Nen Protocol

Oryginalny, grywalny prototyp bijatyki 2D w Pythonie, inspirowany klimatem pojedynków łowców. Grafika jest proceduralna — projekt nie wymaga paczki assetów i nie używa postaci z istniejących serii.

## Co jest w grze

- pojedynek gracz kontra bot albo lokalne 1v1,
- kreator własnej techniki z czterema archetypami,
- automatyczny balans obrażeń, zasięgu, startupu, recovery, aury i cooldownu,
- lekkie i mocne ataki, blok, dash, skok, combosy i regeneracja aury,
- animacje proceduralne, smugi, hit-stop, screen shake, cząsteczki i pociski,
- menu pauzy, restart rundy oraz zapis ostatniej techniki.
- obsługa paczek `*.huntermod.json` bez ponownej instalacji gry.
- multiplayer host/join dla dwóch graczy po TCP,
- angielski interfejs i bardziej szczegółowe postacie w oryginalnym stylu anime.

## Uruchomienie

Wymagany jest Python 3.10 lub nowszy.

```bash
python -m pip install -r requirements.txt
python main.py
```

Jeżeli system używa polecenia `python3`, zamień `python` na `python3`.

Na Windows najlepiej wypakować cały ZIP, a następnie dwukrotnie kliknąć
`start_game.bat`. Launcher sam utworzy lokalne środowisko i zainstaluje Pygame.
Nie uruchamiaj pliku bezpośrednio z podglądu archiwum ZIP.

Na Linuxie/macOS:

```bash
chmod +x start_game.sh
./start_game.sh
```

## Sterowanie

### Gracz 1

| Akcja | Klawisz |
| --- | --- |
| Ruch | A / D |
| Skok | W |
| Blok | F |
| Dash | Q |
| Szybki atak | G |
| Mocny atak | H |
| Własna technika | J |

### Gracz 2 (tryb lokalny)

| Akcja | Klawisz |
| --- | --- |
| Ruch | ← / → |
| Skok | ↑ |
| Blok | Prawy Ctrl |
| Dash | Prawy Shift |
| Szybki atak | Num 1 |
| Mocny atak | Num 2 |
| Własna technika | Num 3 |

`Esc` pauzuje grę. `R` rozpoczyna nową rundę po KO.

## Jak działa balans AI

Kreator przyjmuje fantazję gracza, ale nie pozwala dostać wszystkiego naraz. Suma ustawień ponad budżet 24 punktów automatycznie zwiększa startup, recovery, koszt aury i cooldown. Każdy archetyp dodaje własny czytelny kompromis: Wzmocnienie ma duży burst, Emisja dystans, Transmutacja mobilność, a Manipulacja okno kontry.

Kod reguł znajduje się w `game_core.py`, więc można łatwo dodawać archetypy lub modyfikować wzory bez dotykania renderowania.

## Wersja aplikacji Windows

Gotowy build tworzy pojedynczy `HunterDuel.exe` z własną ikoną. Python i Pygame
nie są wtedy potrzebne na komputerze gracza. Techniki można później dodawać,
kopiując pliki `*.huntermod.json` do folderu `mods` obok aplikacji. Zapis ostatniej
techniki znajduje się w `%APPDATA%\HunterDuel`, więc podmiana EXE go nie usuwa.

Automatyczny build dla Windows znajduje się w `.github/workflows/build-windows.yml`.
Na komputerze z Windowsem można też uruchomić `build_windows.bat`.

## Multiplayer

1. Obaj gracze uruchamiają tę samą wersję gry.
2. Host wybiera `ONLINE MULTIPLAYER` → `CREATE SERVER`.
3. Drugi gracz wpisuje adres IP hosta i wybiera `JOIN SERVER`.
4. W tej samej sieci Wi-Fi użyj lokalnego IP wyświetlonego przez hosta.
5. Przez internet host musi przekierować port TCP `50505` albo obaj gracze
   mogą skorzystać ze wspólnej wirtualnej sieci LAN.

Host jest autorytatywny: oblicza fizykę, trafienia, aurę i wynik rundy. Gość
wysyła wyłącznie sterowanie, a stan walki jest synchronizowany 30 razy na sekundę.

## Zmiany balansu 1.1

Knockback szybkich, mocnych i specjalnych ataków został zwiększony. Każde kolejne
trafienie w combo dodatkowo zwiększa odrzut i skraca hitstun, dlatego długie
pętle są znacznie trudniejsze, a neutral i ustawienie na arenie ważniejsze.

## Testy

```bash
python -m unittest discover -s tests -v
```

Testy balansu nie wymagają Pygame ani otwartego okna.
