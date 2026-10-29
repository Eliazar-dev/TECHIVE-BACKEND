from django.contrib import admin
from .models import Quote, WaitlistEntry


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'service', 'budget', 'status', 'created_at')
    list_filter = ('status', 'service')
    search_fields = ('name', 'email', 'message')
    list_editable = ('status',)


@admin.register(WaitlistEntry)
class WaitlistAdmin(admin.ModelAdmin):
    list_display = ('email', 'name', 'course', 'created_at')
    search_fields = ('email', 'name')
