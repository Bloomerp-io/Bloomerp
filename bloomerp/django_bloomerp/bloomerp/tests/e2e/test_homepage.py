from playwright.sync_api import expect, Page
 

class TestHomepage:
    def test_homepage_redirects_to_login(self, page: Page, live_server_url: str):
        page.goto(live_server_url)
        
        expect(page).to_have_title("Bloomerp")
        expect(page).to_have_url(f"{live_server_url}/login/?next=/")
        expect(page.get_by_role("heading", name="Welcome back")).to_be_visible()
 
    def test_login_form_loads(self, page, live_server_url):
        page.goto(f"{live_server_url}/login/")
 
        expect(page.locator('input[name="username"]')).to_be_visible()
        expect(page.locator('input[name="password"]')).to_be_visible()
        expect(page.get_by_role("button", name="Login")).to_be_visible()
