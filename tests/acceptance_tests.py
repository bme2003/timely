import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime
import time

BASE_URL = "http://127.0.0.1:5000"  # Replace with the actual running server

@pytest.fixture(scope="module")
def driver():
    """Setup and teardown for Selenium WebDriver."""
    driver = webdriver.Chrome()  # Ensure chromedriver is in PATH
    driver.implicitly_wait(10)
    yield driver
    driver.quit()

def test_landing_page(driver):
    driver.get(BASE_URL)
    assert "Timely - Your Study Companion" in driver.title
    assert driver.find_element(By.LINK_TEXT, "Login")
    assert driver.find_element(By.LINK_TEXT, "Sign Up")

def test_signup(driver):
    driver.get(f"{BASE_URL}/signup")
    driver.find_element(By.NAME, "username").send_keys("testuser")
    driver.find_element(By.NAME, "email").send_keys("testuser@example.com")
    driver.find_element(By.NAME, "password").send_keys("Password123")
    driver.find_element(By.NAME, "canvas_ical_url").send_keys("https://example.com/calendar.ics")
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
    assert "Account created successfully!" in driver.page_source

def test_login(driver):
    driver.get(f"{BASE_URL}/login")
    driver.find_element(By.NAME, "username").send_keys("testuser")
    driver.find_element(By.NAME, "password").send_keys("Password123")
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
    assert "Calendar" in driver.title

def test_logout(driver):
    driver.get(f"{BASE_URL}/logout")
    assert "You have been logged out." in driver.page_source

