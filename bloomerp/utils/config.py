from django.conf import settings
import openai
from colorama import Fore, Style

class BloomerpConfigChecker:
    '''Class that checks whether the configuration for bloomerp is correct'''
    settings : dict = settings

    OKAY = 0 # Okay status
    WARNING = 1 # Warning status
    ERROR = 2 # Error status

    def _check_open_ai_key(self) -> tuple[int, str]:
        '''Check if the open ai key is set'''
        openai_key = self.settings.BLOOMERP_SETTINGS.get('OPENAI_API_KEY', None)

        appended_message = 'Without a valid key, the LLM features will not work.'

        if not openai_key:
            return self.WARNING, 'OpenAI key not found in settings' + appended_message
        else:
            # Check if the key is valid
            client = openai.OpenAI(api_key=openai_key)
            try:
                client.models.list()
                return self.OKAY, 'OpenAI key is valid'
            except openai.AuthenticationError:
                return self.WARNING, 'Invalid OpenAI key' + appended_message
            except:
                return self.WARNING, 'Invalid OpenAI key' + appended_message
            

    def _check_login_url(self) -> tuple[int, str]:
        '''Check if the login url is set'''
        login_url = self.settings.LOGIN_URL
        
        if not login_url:
            return self.ERROR, 'Login URL not found in settings'
        
        if login_url != 'login':
            return self.WARNING, 'It is recommended to set the login URL to "login"'
        
        return self.OKAY, 'Login URL is set correctly'

    def _check_auto_link_generator(self) -> tuple[int, str]:
        '''Check if the auto link generator is set'''
        auto_link_generator = self.settings.BLOOMERP_SETTINGS.get('AUTO_GENERATE_LINKS', False)

        if not auto_link_generator:
            msg = '''Auto link generator is not turned on. To enable it, set AUTO_LINK_GENERATOR to True.\nIf you want to manually generate links, you can use the command python manage.py create_links.\nNot recommended to turn on in production.'''

            return self.OKAY, msg
        
        return self.WARNING, 'Auto link generator is turned on. Recommended to set AUTO_LINK_GENERATOR to False in production.'

    def _check_auto_generate_api(self) -> tuple[int, str]:
        '''Check if the auto generate api is set'''
        auto_generate_api = self.settings.BLOOMERP_SETTINGS.get('AUTO_GENERATE_API', False)

        if not auto_generate_api:
            msg = '''Auto generate API is not turned on.'''

            return self.OKAY, msg
        
        return self.OKAY, 'Auto generate API is turned on.'

    def check(self) -> bool:
        '''Check the configuration'''
        print(f'{Fore.BLUE}Checking Bloomerp configuration{Style.RESET_ALL}')
        print('---------------------------------')
        checks = [
            self._check_open_ai_key,
            self._check_login_url,
            self._check_auto_link_generator
        ]

        for check in checks:
            # Get the function name
            name = check.__name__.replace('_check_', '').replace('_', ' ').capitalize()

            status, message = check()
            print(f'{Fore.BLUE}{name}{Style.RESET_ALL}')

            if status == self.OKAY:
                print(f'{Fore.GREEN}OK: {message}{Style.RESET_ALL}')
            elif status == self.WARNING:
                print(f'{Fore.YELLOW}WARNING: {message}{Style.RESET_ALL}')
            else:
                print(f'{Fore.LIGHTRED_EX}ERROR: {message}{Style.RESET_ALL}')

            print('---------------------------------')
        