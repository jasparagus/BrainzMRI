"""Quick test of _clean_title with common version suffixes."""
import sys
sys.path.insert(0, r"c:\Users\jaspe\AppData\Local\Programs\BrainzMRI")
from api_client import MusicBrainzClient

mb = MusicBrainzClient()

tests = [
    "High Roller (Album Version)",
    "Trip Like I Do (Album Version)",
    "Name of the Game (Remastered)",
    "Busy Child (Radio Edit)",
    "Keep Hope Alive (Original Mix)",
    "Born Too Slow (Single Version)",
    "Cherry Twist (LP Version)",
    "Now Is the Time (Clean Version)",
    "Busy Child (Extended Mix)",
    "Name of the Game (Acoustic Version)",
    "High Roller (Remastered 2006)",
    "High Roller",
    "High Roller (feat. Someone)",
]

print(f"{'Input':50s} -> Output")
print("-" * 90)
for t in tests:
    cleaned = mb._clean_title(t)
    changed = " [OK]" if cleaned != t else " [MISSED]"
    print(f"{t:50s} -> {cleaned:30s}{changed}")
