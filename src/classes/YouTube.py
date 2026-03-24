import re
import base64
import json
import time
import os
import requests
import assemblyai as aai

from utils import *
from cache import *
from .Tts import TTS
from llm_provider import generate_text
from config import *
from status import *
from uuid import uuid4
from constants import *
from typing import List

# Fixed MoviePy Imports for Pylance
from moviepy.editor import (
    AudioFileClip, 
    VideoFileClip, 
    TextClip, 
    ImageClip, 
    CompositeVideoClip, 
    CompositeAudioClip, 
    concatenate_videoclips,
    afx
)
from moviepy.video.fx.all import crop
from moviepy.config import change_settings
from moviepy.video.tools.subtitles import SubtitlesClip

from termcolor import colored
from selenium_firefox import *
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from webdriver_manager.firefox import GeckoDriverManager
from datetime import datetime

# Set ImageMagick Path
change_settings({"IMAGEMAGICK_BINARY": get_imagemagick_path()})


class YouTube:
    """
    Class for YouTube Automation.

    Steps to create a YouTube Short:
    1. Generate a topic [DONE]
    2. Generate a script [DONE]
    3. Generate metadata (Title, Description, Tags) [DONE]
    4. Generate AI Image Prompts [DONE]
    4. Generate Images based on generated Prompts [DONE]
    5. Convert Text-to-Speech [DONE]
    6. Show images each for n seconds, n: Duration of TTS / Amount of images [DONE]
    7. Combine Concatenated Images with the Text-to-Speech [DONE]
    """

    def __init__(
        self,
        account_uuid: str,
        account_nickname: str,
        fp_profile_path: str,
        niche: str,
        language: str,
    ) -> None:
        """
        Constructor for YouTube Class.
        """
        self._account_uuid: str = account_uuid
        self._account_nickname: str = account_nickname
        self._fp_profile_path: str = fp_profile_path
        self._niche: str = niche
        self._language: str = language

        self.images = []

        # Initialize the Firefox profile
        self.options: Options = Options()

        # Set headless state of browser
        if get_headless():
            self.options.add_argument("--headless")

        if not os.path.isdir(self._fp_profile_path):
            raise ValueError(
                f"Firefox profile path does not exist or is not a directory: {self._fp_profile_path}"
            )

        self.options.add_argument("-profile")
        self.options.add_argument(self._fp_profile_path)

        # Set the service
        self.service: Service = Service(GeckoDriverManager().install())

        # Initialize the browser
        self.browser: webdriver.Firefox = webdriver.Firefox(
            service=self.service, options=self.options
        )

    @property
    def niche(self) -> str:
        return self._niche

    @property
    def language(self) -> str:
        return self._language

    def generate_response(self, prompt: str, model_name: str = None) -> str:
        return generate_text(prompt, model_name=model_name)

    def generate_topic(self) -> str:
        completion = self.generate_response(
            f"Please generate a specific video idea that takes about the following topic: {self.niche}. Make it exactly one sentence. Only return the topic, nothing else."
        )

        if not completion:
            error("Failed to generate Topic.")

        self.subject = completion
        return completion

    def generate_script(self) -> str:
        sentence_length = get_script_sentence_length()
        prompt = f"""
        Generate a script for a video in {sentence_length} sentences.
        Subject: {self.subject}
        Language: {self.language}
        """
        completion = self.generate_response(prompt)
        completion = re.sub(r"\*", "", completion)

        if not completion:
            error("The generated script is empty.")
            return

        if len(completion) > 5000:
            if get_verbose():
                warning("Generated Script is too long. Retrying...")
            return self.generate_script()

        self.script = completion
        return completion

    def generate_metadata(self) -> dict:
        title = self.generate_response(
            f"Please generate a YouTube Video Title for: {self.subject}. Limit under 100 characters."
        )

        if len(title) > 100:
            return self.generate_metadata()

        description = self.generate_response(
            f"Please generate a description for: {self.script}."
        )

        self.metadata = {"title": title, "description": description}
        return self.metadata

    def generate_prompts(self) -> List[str]:
        n_prompts = len(self.script) / 3
        prompt = f"Generate {n_prompts} Image Prompts for JSON: {self.script}"
        
        completion = (
            str(self.generate_response(prompt))
            .replace("```json", "")
            .replace("```", "")
        )

        image_prompts = []
        try:
            image_prompts = json.loads(completion)
        except:
            r = re.compile(r"\[.*\]")
            image_prompts = r.findall(completion)
            if not image_prompts: return self.generate_prompts()

        self.image_prompts = image_prompts
        success(f"Generated {len(image_prompts)} Image Prompts.")
        return image_prompts

    def _persist_image(self, image_bytes: bytes, provider_label: str) -> str:
        image_path = os.path.join(ROOT_DIR, ".mp", str(uuid4()) + ".png")
        with open(image_path, "wb") as image_file:
            image_file.write(image_bytes)
        self.images.append(image_path)
        return image_path

    def generate_image_nanobanana2(self, prompt: str) -> str:
        # Implementation of Nano Banana 2 (Gemini Image API)
        api_key = get_nanobanana2_api_key()
        base_url = get_nanobanana2_api_base_url().rstrip("/")
        model = get_nanobanana2_model()
        
        endpoint = f"{base_url}/models/{model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {"aspectRatio": get_nanobanana2_aspect_ratio()},
            },
        }

        try:
            response = requests.post(endpoint, headers={"x-goog-api-key": api_key}, json=payload)
            body = response.json()
            data = body["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            image_bytes = base64.b64decode(data)
            return self._persist_image(image_bytes, "Nano Banana 2")
        except Exception as e:
            warning(f"Image generation failed: {e}")
            return None

    def generate_image(self, prompt: str) -> str:
        return self.generate_image_nanobanana2(prompt)

    def generate_script_to_speech(self, tts_instance: TTS) -> str:
        path = os.path.join(ROOT_DIR, ".mp", str(uuid4()) + ".wav")
        self.script = re.sub(r"[^\w\s.?!]", "", self.script)
        tts_instance.synthesize(self.script, path)
        self.tts_path = path
        return path

    def generate_subtitles(self, audio_path: str) -> str:
        provider = str(get_stt_provider() or "local_whisper").lower()
        if provider == "third_party_assemblyai":
            return self.generate_subtitles_assemblyai(audio_path)
        return self.generate_subtitles_local_whisper(audio_path)

    def generate_subtitles_assemblyai(self, audio_path: str) -> str:
        aai.settings.api_key = get_assemblyai_api_key()
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(audio_path)
        srt_path = os.path.join(ROOT_DIR, ".mp", str(uuid4()) + ".srt")
        with open(srt_path, "w") as file:
            file.write(transcript.export_subtitles_srt())
        return srt_path

    def _format_srt_timestamp(self, seconds: float) -> str:
        total_millis = max(0, int(round(seconds * 1000)))
        hours = total_millis // 3600000
        minutes = (total_millis % 3600000) // 60000
        secs = (total_millis % 60000) // 1000
        millis = total_millis % 1000
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def generate_subtitles_local_whisper(self, audio_path: str) -> str:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            error("faster-whisper not found.")
            raise

        model = WhisperModel(get_whisper_model(), device=get_whisper_device())
        segments, _ = model.transcribe(audio_path)

        lines = []
        for idx, segment in enumerate(segments, start=1):
            start = self._format_srt_timestamp(segment.start)
            end = self._format_srt_timestamp(segment.end)
            lines.extend([str(idx), f"{start} --> {end}", segment.text.strip(), ""])

        srt_path = os.path.join(ROOT_DIR, ".mp", str(uuid4()) + ".srt")
        with open(srt_path, "w", encoding="utf-8") as file:
            file.write("\n".join(lines))
        return srt_path

    def combine(self) -> str:
        combined_image_path = os.path.join(ROOT_DIR, ".mp", str(uuid4()) + ".mp4")
        tts_clip = AudioFileClip(self.tts_path)
        max_duration = tts_clip.duration
        req_dur = max_duration / len(self.images)

        generator = lambda txt: TextClip(
            txt, font=os.path.join(get_fonts_dir(), get_font()),
            fontsize=100, color="#FFFF00", stroke_color="black", stroke_width=5,
            size=(1080, 1920), method="caption"
        )

        clips = []
        tot_dur = 0
        while tot_dur < max_duration:
            for image_path in self.images:
                clip = ImageClip(image_path).set_duration(req_dur).set_fps(30)
                # Resize logic for 9:16
                if round((clip.w / clip.h), 4) < 0.5625:
                    clip = crop(clip, width=clip.w, height=round(clip.w / 0.5625), x_center=clip.w/2, y_center=clip.h/2)
                else:
                    clip = crop(clip, width=round(0.5625 * clip.h), height=clip.h, x_center=clip.w/2, y_center=clip.h/2)
                
                clips.append(clip.resize((1080, 1920)))
                tot_dur += clip.duration

        final_clip = concatenate_videoclips(clips).set_fps(30)
        
        # Audio Mix
        random_song = AudioFileClip(choose_random_song()).volumex(0.1).set_duration(max_duration)
        comp_audio = CompositeAudioClip([tts_clip, random_song])
        final_clip = final_clip.set_audio(comp_audio)

        # Subtitles Overlay
        try:
            sub_path = self.generate_subtitles(self.tts_path)
            subtitles = SubtitlesClip(sub_path, generator).set_pos(("center", "center"))
            final_clip = CompositeVideoClip([final_clip, subtitles])
        except Exception as e:
            warning(f"Subtitles error: {e}")

        final_clip.write_videofile(combined_image_path, threads=get_threads())
        return combined_image_path

    def generate_video(self, tts_instance: TTS) -> str:
        self.generate_topic()
        self.generate_script()
        self.generate_metadata()
        self.generate_prompts()
        for prompt in self.image_prompts:
            self.generate_image(prompt)
        self.generate_script_to_speech(tts_instance)
        path = self.combine()
        self.video_path = os.path.abspath(path)
        return path

    def get_channel_id(self) -> str:
        self.browser.get("https://studio.youtube.com")
        time.sleep(2)
        channel_id = self.browser.current_url.split("/")[-1]
        return channel_id

    def upload_video(self) -> bool:
        # Shortened for space, logic continues here...
        pass