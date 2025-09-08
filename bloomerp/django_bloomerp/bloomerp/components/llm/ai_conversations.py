from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from django.contrib.auth.decorators import login_required
from bloomerp.models import AIConversation
import uuid
from bloomerp.utils.requests import parse_bool_parameter
from django.utils import timezone

@login_required
@route('ai_conversations')
def ai_conversations(request:HttpRequest) -> HttpResponse:
    '''Component that renders ai conversation or a single conversation.

    Args:
        request (HttpRequest): The request object

    GET Parameters:
        target (str): The target to render
        conversation_id (str): The conversation id
        conversation_type (str): The conversation type
        new_conversation (bool): Create a new conversation
        delete (bool): Delete the conversation
        rename (str): Rename the conversation
        args (str): The arguments to be passed to the llm executor
        latest (bool): Get the latest conversation

    Returns:
        HttpResponse: The response object
    '''
    target = request.GET.get('target', None)
    conversation_id = request.GET.get('conversation_id', None)
    conversation_type = request.GET.get('conversation_type', None)
    new_conversation = parse_bool_parameter(request.GET.get('new_conversation'), False)
    delete = parse_bool_parameter(request.GET.get('delete'), False)
    rename = request.GET.get('rename', None)
    args = request.GET.get('args', None)
    latest = parse_bool_parameter(request.GET.get('latest'), False)


    if latest:
        ai_conversations = AIConversation.objects.filter(
            user = request.user,
            conversation_type=conversation_type,
            datetime_updated__gte=timezone.now() - timezone.timedelta(minutes=30)
        ).order_by('-datetime_updated')

        if ai_conversations.exists():
            ai_conversation_object = ai_conversations.first()
        else:
            ai_conversation_object = get_new_conversation(request.user, conversation_type)
        return render(request, 'components/llm/ai_conversation.html', {'ai_conversation': ai_conversation_object, 'target': target, 'args': args})
        

    # Check if the conversation id is provided
    if new_conversation:
        # Check if there are any existing conversations with no messages
        ai_conversation_object = get_new_conversation(request.user, conversation_type)
        return render(request, 'components/llm/ai_conversation.html', {'ai_conversation': ai_conversation_object, 'target': target, 'args': args})

    # In cases of no conversation id
    elif not conversation_id:
        ai_conversations = AIConversation.objects.filter(
        user = request.user,
        conversation_type=conversation_type
        ).order_by('-datetime_created')

        context = {
            'ai_conversations': ai_conversations,
            'target': target,
            'args': args
        }
        return render(request, 'components/llm/ai_conversations.html', context) 

    else:
        if delete:
            try:
                id = uuid.UUID(conversation_id)
                ai_conversation_object = AIConversation.objects.get(id=id)
                ai_conversation_object.delete()
            except:
                return HttpResponse('Invalid conversation id')

            conversations = filter_ai_conversations(request.user, conversation_type)

            return render(request, 'components/llm/ai_conversations.html', {'ai_conversations': conversations, 'target': target, 'args': args})        

        if rename:
            try:
                id = uuid.UUID(conversation_id)
                ai_conversation_object = AIConversation.objects.get(id=id)
                ai_conversation_object.title = rename
                ai_conversation_object.save()
            except:
                return HttpResponse('Invalid conversation id')

            conversations = filter_ai_conversations(request.user, conversation_type)

            return render(request, 'components/llm/ai_conversations.html', {'ai_conversations': conversations, 'target': target, 'args': args})


        # Parse uuid
        try:
            id = uuid.UUID(conversation_id)
            ai_conversation_object = AIConversation.objects.get(id=id)
        except:
            return HttpResponse('Invalid conversation id')
        
        # Get the AIConversation object
        return render(request, 'components/llm/ai_conversation.html', {'ai_conversation': ai_conversation_object, 'target': target, 'args': args})


def filter_ai_conversations(user, conversation_type:str):
    '''Filter AI conversations by user and conversation type.

    Args:
        user (User): The user object
        conversation_type (str): The conversation type

    Returns:
        QuerySet: The query set of AI conversations
    '''
    return AIConversation.objects.filter(
        user = user,
        conversation_type=conversation_type
    ).order_by('-datetime_created')


def get_new_conversation(user, conversation_type:str):
    '''Get a new conversation object.

    Args:
        user (User): The user object
        conversation_type (str): The conversation type

    Returns:
        AIConversation: The AI conversation object
    '''
    ai_conversations = AIConversation.objects.filter(
            user = user,
            conversation_type=conversation_type,
            conversation_history__isnull=True
        )

    if ai_conversations.exists():
        ai_conversation_object = ai_conversations.first()
    else:
        ai_conversation_object = AIConversation.objects.create(
            user = user,
            conversation_type = conversation_type
        )

    return ai_conversation_object