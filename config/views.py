from django.http import HttpResponse
from django.shortcuts import render


# Create your views here.
def links(request):
    return HttpResponse('links')

