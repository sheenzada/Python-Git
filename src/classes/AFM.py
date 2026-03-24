import os
from urllib.parse import urlparse
from typing import Any

from status import *
from config import *
from constants import *
from llm_provider import generate_text
from .Twitter import Twitter

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from webdriver_manager.firefox import GeckoDriverManager


class AffiliateMarketing:
    """
    This class will be used to handle all the affiliate marketing related operations.
    """

    def __init__(
        self,
        affiliate_link: str,
        fp_profile_path: str,
        twitter_account_uuid: str,
        account_nickname: str,
        topic: str,
    ) -> None:

        self._fp_profile_path: str = fp_profile_path

        # Initialize Firefox options
        self.options: Options = Options()

        # Headless mode
        if get_headless():
            self.options.add_argument("--headless")

        # Validate profile path
        if not os.path.isdir(fp_profile_path):
            raise ValueError(
                f"Firefox profile path does not exist: {fp_profile_path}"
            )

        # Load Firefox profile
        self.options.add_argument("-profile")
        self.options.add_argument(fp_profile_path)

        # Setup driver
        self.service: Service = Service(GeckoDriverManager().install())

        self.browser: webdriver.Firefox = webdriver.Firefox(
            service=self.service,
            options=self.options
        )

        # Validate affiliate link
        self.affiliate_link: str = affiliate_link
        parsed_link = urlparse(self.affiliate_link)

        if parsed_link.scheme not in ["http", "https"] or not parsed_link.netloc:
            raise ValueError(f"Invalid affiliate link: {self.affiliate_link}")

        # Account info
        self.account_uuid: str = twitter_account_uuid
        self.account_nickname: str = account_nickname
        self.topic: str = topic

        # Scrape product info
        self.scrape_product_information()

    def scrape_product_information(self) -> None:
        """Scrape product data from affiliate link"""

        self.browser.get(self.affiliate_link)

        # Product title
        product_title: str = self.browser.find_element(
            By.ID, AMAZON_PRODUCT_TITLE_ID
        ).text

        # Features (FIXED: now extracts text properly)
        features = [
            el.text for el in self.browser.find_elements(
                By.ID, AMAZON_FEATURE_BULLETS_ID
            )
        ]

        if get_verbose():
            info(f"Product Title: {product_title}")
            info(f"Features: {features}")

        self.product_title: str = product_title
        self.features: Any = features

    def generate_response(self, prompt: str) -> str:
        return generate_text(prompt)

    def generate_pitch(self) -> str:
        pitch: str = (
            self.generate_response(
                f'I want to promote this product on my website. Generate a brief pitch only.\n'
                f'Title: "{self.product_title}"\n'
                f'Features: "{self.features}"'
            )
            + "\nYou can buy the product here: "
            + self.affiliate_link
        )

        self.pitch: str = pitch
        return pitch

    def share_pitch(self, where: str) -> None:
        if where == "twitter":
            twitter: Twitter = Twitter(
                self.account_uuid,
                self.account_nickname,
                self._fp_profile_path,
                self.topic,
            )
            twitter.post(self.pitch)

    def quit(self) -> None:
        self.browser.quit()