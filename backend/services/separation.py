import subprocess
import sys
from pathlib import Path
import logging

class SeparationService:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)

    async def separate_audio(self, input_path: Path, model_name: str = "htdemucs_6s"):
        """
        Separates audio into stems using Demucs (htdemucs_6s) in a single pass.
        This provides coherent separation for Vocals, Drums, Bass, Guitar, Piano, Other.
        """
        self.logger.info(f"Starting separation for {input_path} using {model_name}")
        
        try:
            # Define output format
            track_name = input_path.stem
            output_folder = self.output_dir / track_name
            output_folder.mkdir(parents=True, exist_ok=True)
            
            # Use native Demucs directly for the entire pipeline.
            # It is robust, coherent, and supports 6 stems.
            # Command: demucs -n htdemucs_6s -o {output_folder} {input_path}
            
            # Command: python -m demucs.separate -n htdemucs_6s -o {output_folder} {input_path}
            # Using sys.executable ensures we use the current venv's python
            cmd = [
                sys.executable, "-m", "demucs.separate",
                "-n", "htdemucs_6s",
                "-o", str(output_folder),
                str(input_path)
            ]
            
            self.logger.info(f"Running command: {' '.join(cmd)}")
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Demucs separation failed: {e.stderr}")
                raise e

            # Demucs output structure: output_folder/htdemucs_6s/{track_name}/...
            demucs_out_dir = output_folder / "htdemucs_6s" / track_name
            
            self.logger.info(f"Looking for stems in: {demucs_out_dir}")
            
            stems = {}
            if demucs_out_dir.exists():
                for f in demucs_out_dir.iterdir():
                    if f.suffix.lower() != ".wav": continue
                    
                    lname = f.name.lower()
                    # HTDemucs_6s outputs: drums, bass, other, vocals, guitar, piano
                    if "drums" in lname:
                        stems["drums"] = f
                    elif "bass" in lname:
                        stems["bass"] = f
                    elif "guitar" in lname:
                        stems["guitar"] = f
                    elif "piano" in lname:
                        stems["piano"] = f
                    elif "vocals" in lname or "vocal" in lname:
                        stems["vocals"] = f
                    elif "other" in lname:
                        stems["other"] = f
            else:
                 self.logger.warning(f"Demucs output directory not found: {demucs_out_dir}")
                        
            self.logger.info(f"Stems found: {list(stems.keys())}")
            
            return stems

        except Exception as e:
            self.logger.error(f"Separation failed: {e}")
            raise e
