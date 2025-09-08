from django.conf import settings
from langchain_core.messages import (
    HumanMessage, 
    SystemMessage, 
    ToolMessage, 
    BaseMessage,
    AIMessage,
    messages_from_dict,
    messages_to_dict
    )
from langchain_core.chat_history import InMemoryChatMessageHistory
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.graph.graph import CompiledGraph
from django.core.cache import cache
from langchain_core.tools import StructuredTool
from bloomerp.langchain_tools import BaseBloomerpTool
from pydantic import BaseModel, Field


class BloomerpLangChain:
    '''Class to invoke the Bloom AI agent.''' 
    conversation_history : list
    invoked: bool = False

    def __init__(self, 
                 api_key:str=None, 
                 conversation_history:list = None,
                 user=None
                 ):
        '''
        Args:
            api_key: The OpenAI API key.
            conversation_history: The conversation history.
        '''
        self.api_key = api_key
        self.conversation_history = conversation_history
        self.model = ChatOpenAI(model="gpt-4o-mini", api_key=api_key)
        self.user = user

    def invoke_tiny_mce_content(self, query:str):
        '''Invoke the TinyMCE content agent.'''

        SYSTEM_CONTENT = '''You are a helpful assistant that helps me to create content for TinyMCE editor based on the prompt it gives.
        The output should be the content that can be used in TinyMCE editor, meaning it should be formatted as HTML.
        '''

        # Prepare messages for the OpenAI API
        messages = self._prepare_messages(query, SYSTEM_CONTENT)

        # Create the agent
        memory = MemorySaver()
        agent = create_react_agent(self.model, tools=[], checkpointer=memory)

        # Invoke the model
        for chunk in self._invoke_model(messages, agent):
            yield chunk
    
    def invoke_sql_query(self, query:str, db_tables_and_columns:list[tuple[str, list[str]]]):
        '''Invoke the SQL query agent.'''

        # Prepare system content
        SYSTEM_CONTENT = '''You are a helpful assistant that helps me to create SQL queries from natural language.
        The output should be a SQL query using sqlite3 syntax, without any explanation. Dont include in the output ```sql ... ```, just the raw SQL query.
        Here are the database tables, columns and datatypes for each column in the database:
        '''

        for table in db_tables_and_columns:
            SYSTEM_CONTENT += f'\n{table[0]}: '

            for column in table[1]:
                SYSTEM_CONTENT += f'{column[0]} ({column[1]}), '

        # Prepare messages for the OpenAI API
        messages = self._prepare_messages(query, SYSTEM_CONTENT)

        # Create the agent
        memory = MemorySaver()
        agent = create_react_agent(self.model, tools=[], checkpointer=memory)

        # Invoke the model
        for chunk in self._invoke_model(messages, agent):
            yield chunk
        
    def invoke_bloom_ai(self, query:str, tools:list[StructuredTool], user=None):
        '''Invoke the Bloom AI agent.'''

        SYSTEM_CONTENT = f'''You are an AI agent for a ERP system called Bloomerp.
        Your job is to help users with their day-to-day job, which can include answering to queries. 
        You can use the tools provided to you to get information from the database and provide it to the user.
        If you need to get information from the database, you can use the tool get_database_tables to get the tables and their columns in the database, but please only call this once per conversation.
        '''

        # Prepare messages for the OpenAI API
        # Used to save the state of the conversation
        memory = MemorySaver()

        initialized_tools = []
        for tool in tools:
            # Check if the tool has attribute requires_user
            if issubclass(tool, BaseBloomerpTool):
                initialized_tools.append(tool(user=user))
            else:
                initialized_tools.append(tool())


        # Create the agent
        agent = create_react_agent(self.model, tools=initialized_tools, checkpointer=memory)

        # Prepare messages
        messages = self._prepare_messages(query, SYSTEM_CONTENT)

        # Invoke the model
        for chunk in self._invoke_model(messages, agent):
            yield chunk

    def invoke_object_bloom_ai(self, query:str, tools:list[StructuredTool], object_representation:str, user=None):
        '''Invoke the Bloom AI agent for an object.'''

        SYSTEM_CONTENT = f'''You are an AI agent for a ERP system called Bloomerp.
        Your job is to help users with their day-to-day job, which can include answering to queries. 
        You can use the tools provided to you to get information from the database and provide it to the user.
        If you need to get information from the database, you can use the tool get_database_tables to get the tables and their columns in the database, but please only call this once per conversation.
        '''
        SYSTEM_CONTENT += f'\n\n you are currently working with the following object:'
        SYSTEM_CONTENT += f'\n{object_representation}'


        # Prepare messages for the OpenAI API
        # Used to save the state of the conversation
        memory = MemorySaver()

        initialized_tools = []
        for tool in tools:
            # Check if the tool has attribute requires_user
            if issubclass(tool, BaseBloomerpTool):
                initialized_tools.append(tool(user=user))
            else:
                initialized_tools.append(tool())

        # Create the agent
        agent = create_react_agent(self.model, tools=initialized_tools, checkpointer=memory)

        # Prepare messages
        messages = self._prepare_messages(query, SYSTEM_CONTENT)

        # Invoke the model
        for chunk in self._invoke_model(messages, agent):
            yield chunk

    def invoke_code(self, query:str):
        '''Invoke the code agent.'''

        SYSTEM_CONTENT = '''You are a helpful assistant that helps me to create code from natural language.
        Only return the actual code snippet without giving any explanation.
        Don't include any markdown code blocks in the output.
        '''

        # Prepare messages for the OpenAI API
        messages = self._prepare_messages(query, SYSTEM_CONTENT)

        # Create the agent
        memory = MemorySaver()
        agent = create_react_agent(self.model, tools=[], checkpointer=memory)

        # Invoke the model
        for chunk in self._invoke_model(messages, agent):
            yield chunk

    def invoke_document_template(self, query:str, variables:list[(str, str, str)]):
        '''Invoke the document template agent.'''

        SYSTEM_CONTENT = '''
        You are a helpful assistant that helps me to create document templates from natural language.
        The output should be the document (in html) using jinja2 (Django template) syntax, without any explanation. Dont include in the output ```html ... ```, just the raw HTML.
        For object variables, use the following syntax: {{ object.variable_name }}
        For free variables, use the following syntax: {{ free_variable_name }}

        Here are the available variables that you can use in the document template:
        '''
        for variable in variables:
            SYSTEM_CONTENT += f'\n{variable[0]} ({variable[1]}) - {variable[2]}'

        # Prepare messages for the OpenAI API
        messages = self._prepare_messages(query, SYSTEM_CONTENT)

        # Create the agent
        memory = MemorySaver()
        agent = create_react_agent(self.model, tools=[], checkpointer=memory)

        # Invoke the model
        for chunk in self._invoke_model(messages, agent):
            yield chunk

    def serialize_conversation_history(self) -> list[dict]:
        '''Make the conversation history JSON serializable.'''
        if self.conversation_history:
            return messages_to_dict(self.conversation_history)
        else:
            return []

    def _parse_conversation_history(self) -> InMemoryChatMessageHistory:
        '''Parse the conversation history into InMemoryChatMessageHistory.'''
        try:
            if self.conversation_history:
                return InMemoryChatMessageHistory(messages=messages_from_dict(self.conversation_history))    
            else:
                return InMemoryChatMessageHistory()
        except Exception as e:
            return InMemoryChatMessageHistory()

    def _invoke_model(self, messages:InMemoryChatMessageHistory, agent:CompiledGraph):
        '''Invoke the model.'''
        
        # This should be investigated in the future
        config = {"configurable": {"thread_id": "abc123"}}

        # Execute the agent
        for chunk in agent.stream(
            input=messages, config=config, stream_mode='messages'
        ):  
            if type(chunk[0]) == ToolMessage:
                tool_name : str = chunk[0].name
                tool_name = tool_name.replace('_', ' ').capitalize()
                yield f" *Calling '{tool_name}' tool.* "
            else:
                result = chunk[0].content
                yield result

        # Set invoked to True
        self.invoked = True

        # Save the conversation history
        messages : list[BaseMessage] = agent.checkpointer.get(config)['channel_values']['messages']

        # Set the conversation history
        self.conversation_history = messages

    def _prepare_messages(self, query:str, system_content:str) -> InMemoryChatMessageHistory:
        '''Prepares messages using the conversation history.
        
        Args:
            query: The user query.
            system_content: The system content.

        Returns:
            InMemoryChatMessageHistory: The conversation history.
        '''
        messages = self._parse_conversation_history()

        if not messages.messages:
            system_content = self.get_standard_system_context() + system_content
            messages.add_message(SystemMessage(system_content))
        
        messages.add_message(HumanMessage(query))

        return messages
    
    def auto_name(self):
        '''Automatically provides a title for a conversation history.'''
        
        class ConversationName(BaseModel):
            title : str = Field(max_length=80)

        SYSTEM_CONTENT = '''Your goal is give a title to a conversation history based on the conversation that happened.
        the title should be max 80 characters long and should be a summary of the conversation that happened.
        '''
        # Prepare messages
        messages = self._parse_conversation_history()

        messages.add_message(SystemMessage(SYSTEM_CONTENT))

        structured_llm = self.model.with_structured_output(ConversationName)

        # Execute
        return structured_llm.invoke(messages.messages).dict()['title']

    def get_standard_system_context(self):
        '''Get the standard context for the conversation.'''
        from django.utils.timezone import now

        SYSTEM_CONTEXT = f'Current time: {now()}\n'

        if self.user:
            try:
                SYSTEM_CONTEXT += f'Full name of user: {self.user.get_full_name()} | User ID: {self.user.id}\n | Username of user: {self.user.username} | Email of user: {self.user.email}\n'
            except:
                pass
        return SYSTEM_CONTEXT
        
