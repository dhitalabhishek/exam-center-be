from locust import HttpUser, TaskSet, task, between
import json
import random


class AuthenticatedExamUser(HttpUser):
    """
    Exam user with proper authentication using real test credentials
    """

    def on_start(self):
        """Called when user starts - authenticate with real credentials"""
        self.authenticated = False
        self.access_token = None
        self.attempt_login()

    def attempt_login(self):
        """Login with real test credentials"""
        # Real test credentials from your system
        test_credentials = [
            {"symbol_number": "13-S14-PH", "password": "U4XXkUOA"},
            {"symbol_number": "13-S13-PH", "password": "8UsSBf2L"},
            {"symbol_number": "13-S12-PH", "password": "dZXypDOR"},
            {"symbol_number": "13-S11-PH", "password": "XMVJmjuT"},
            {"symbol_number": "13-S10-PH", "password": "2Cq14w0x"},
        ]

        cred = random.choice(test_credentials)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        with self.client.post(
            "/api/login/student/",
            json=cred,
            headers=headers,
            catch_response=True,
            name="Student Login",
        ) as response:
            if response.status_code == 200:
                try:
                    response_data = response.json()

                    # Extract access token (adjust key names based on your API response)
                    if "access_token" in response_data:
                        self.access_token = response_data["access_token"]
                    elif "access" in response_data:
                        self.access_token = response_data["access"]
                    elif "token" in response_data:
                        self.access_token = response_data["token"]
                    else:
                        # Print response to see what keys are available
                        print(f"Login response keys: {list(response_data.keys())}")
                        self.access_token = None

                    if self.access_token:
                        # Set authorization header for future requests
                        self.client.headers.update(
                            {"Authorization": f"Bearer {self.access_token}"}
                        )
                        self.authenticated = True
                        print(
                            f"✓ Successfully authenticated as {cred['symbol_number']}"
                        )
                        response.success()
                    else:
                        print(
                            f"⚠ Login successful but no token found for {cred['symbol_number']}"
                        )
                        print(f"Response: {response.text}")
                        response.success()  # Still count as success

                except json.JSONDecodeError:
                    print(
                        f"⚠ Login successful but response is not JSON: {response.text}"
                    )
                    response.success()

            elif response.status_code == 400:
                print(f"✗ Bad request for {cred['symbol_number']}: {response.text}")
                response.failure("Login bad request - check credential format")
            elif response.status_code == 401:
                print(f"✗ Invalid credentials for {cred['symbol_number']}")
                response.success()  # Expected for load testing
            else:
                print(
                    f"✗ Unexpected login status {response.status_code}: {response.text}"
                )
                response.failure(f"Unexpected login status: {response.status_code}")

    def get_auth_headers(self):
        """Get headers with authentication"""
        headers = {"Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    @task(2)
    def get_exam_session(self):
        """Get exam session details"""
        if not self.authenticated:
            return

        with self.client.get(
            "/api/exam/session/",
            headers=self.get_auth_headers(),
            catch_response=True,
            name="Get Exam Session",
        ) as response:
            if response.status_code == 200:
                response.success()
                # Optional: print session data for debugging
                # print(f"Session data: {response.text[:200]}")
            elif response.status_code == 401:
                print("Session request unauthorized - token may have expired")
                self.attempt_login()  # Re-authenticate
                response.success()  # Don't count as failure
            else:
                response.failure(f"Session request failed: {response.status_code}")

    @task(8)
    def get_question_page_1(self):
        """Get first question (most accessed)"""
        self._get_question_page(1)

    @task(6)
    def get_question_page_2(self):
        """Get second question"""
        self._get_question_page(2)

    @task(4)
    def get_question_page_3(self):
        """Get third question"""
        self._get_question_page(3)

    @task(3)
    def get_question_page_random(self):
        """Get random question page"""
        page = random.randint(1, 10)
        self._get_question_page(page)

    def _get_question_page(self, page_num):
        """Helper to get specific question page"""
        if not self.authenticated:
            return

        with self.client.get(
            f"/api/exam/questions/?page={page_num}",
            headers=self.get_auth_headers(),
            catch_response=True,
            name=f"Get Question Page {page_num}",
        ) as response:
            if response.status_code == 200:
                response.success()
                # Optional: print question data for debugging
                # print(f"Question page {page_num}: {response.text[:100]}")
            elif response.status_code == 404:
                # Page doesn't exist - normal for higher page numbers
                response.success()
            elif response.status_code == 401:
                print(f"Question page {page_num} unauthorized - re-authenticating")
                self.attempt_login()
                response.success()
            else:
                response.failure(
                    f"Question page {page_num} failed: {response.status_code}"
                )

    wait_time = between(5, 15)  # Realistic exam taking pace


class LoginTestUser(HttpUser):
    """
    Focus on testing login endpoint thoroughly
    """

    @task
    def test_valid_login(self):
        """Test with valid credentials"""
        valid_credentials = [
            {"symbol_number": "13-S14-PH", "password": "U4XXkUOA"},
            {"symbol_number": "13-S13-PH", "password": "8UsSBf2L"},
            {"symbol_number": "13-S12-PH", "password": "dZXypDOR"},
            {"symbol_number": "13-S11-PH", "password": "XMVJmjuT"},
            {"symbol_number": "13-S10-PH", "password": "2Cq14w0x"},
        ]

        cred = random.choice(valid_credentials)

        with self.client.post(
            "/api/login/student/",
            json=cred,
            headers={"Content-Type": "application/json"},
            catch_response=True,
            name="Valid Login Test",
        ) as response:
            if response.status_code == 200:
                response.success()
                print(f"✓ Valid login successful: {cred['symbol_number']}")
            else:
                print(f"✗ Valid login failed: {response.status_code} - {response.text}")
                response.failure(f"Valid login failed: {response.status_code}")

    @task
    def test_invalid_login(self):
        """Test with invalid credentials (should return 401)"""
        invalid_credentials = [
            {"symbol_number": "13-S99-PH", "password": "wrongpass"},
            {"symbol_number": "invalid-format", "password": "test123"},
            {"symbol_number": "13-S14-PH", "password": "wrongpassword"},
        ]

        cred = random.choice(invalid_credentials)

        with self.client.post(
            "/api/login/student/",
            json=cred,
            headers={"Content-Type": "application/json"},
            catch_response=True,
            name="Invalid Login Test",
        ) as response:
            if response.status_code == 401:
                response.success()  # Expected for invalid creds
            elif response.status_code == 400:
                response.success()  # Also acceptable for malformed requests
            else:
                response.failure(
                    f"Unexpected invalid login response: {response.status_code}"
                )

    wait_time = between(1, 3)


class RealisticExamSession(HttpUser):
    """
    Simulates a complete exam session
    """

    def on_start(self):
        """Start exam session"""
        self.login_and_start_exam()

    def login_and_start_exam(self):
        """Login and get session details"""
        credentials = [
            {"symbol_number": "13-S14-PH", "password": "U4XXkUOA"},
            {"symbol_number": "13-S13-PH", "password": "8UsSBf2L"},
            {"symbol_number": "13-S12-PH", "password": "dZXypDOR"},
            {"symbol_number": "13-S11-PH", "password": "XMVJmjuT"},
            {"symbol_number": "13-S10-PH", "password": "2Cq14w0x"},
        ]

        cred = random.choice(credentials)

        # Login
        login_response = self.client.post(
            "/api/login/student/",
            json=cred,
            headers={"Content-Type": "application/json"},
        )

        if login_response.status_code == 200:
            try:
                login_data = login_response.json()
                token = None

                # Find the token in response
                for key in ["access_token", "access", "token"]:
                    if key in login_data:
                        token = login_data[key]
                        break

                if token:
                    self.client.headers.update({"Authorization": f"Bearer {token}"})
                    self.authenticated = True
                    print(f"✓ Authenticated for exam session: {cred['symbol_number']}")

                    # Get session details immediately after login
                    self.client.get("/api/exam/session/")
                else:
                    self.authenticated = False

            except json.JSONDecodeError:
                self.authenticated = False
        else:
            self.authenticated = False

    @task
    def take_exam_sequence(self):
        """Simulate taking exam in sequence"""
        if not hasattr(self, "authenticated") or not self.authenticated:
            return

        # Simulate going through exam questions in order
        num_questions = random.randint(5, 15)

        for page in range(1, num_questions + 1):
            response = self.client.get(f"/api/exam/questions/?page={page}")

            if response.status_code == 404:
                # No more questions
                break
            elif response.status_code == 401:
                # Need to re-authenticate
                self.login_and_start_exam()
                break

            # Simulate reading time
            self.wait()

    wait_time = between(10, 30)  # Realistic exam pace
