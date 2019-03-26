from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone

from wagtail.core.models import Page

from wagtail_i18n.models import get_translatable_models, TranslatablePageMixin

from .forms import CreateTranslationRequestForm
from .models import TranslationRequest, TranslationRequestPage


def create_translation_request(request, page_id):
    page = get_object_or_404(Page, id=page_id).specific

    if not isinstance(page, TranslatablePageMixin):
        raise Http404

    if request.method == 'POST':
        form = CreateTranslationRequestForm(page, request.POST)

        if form.is_valid():
            with transaction.atomic():
                source_locale = page.locale
                revision = page.get_latest_revision()
                translatable_models = tuple(get_translatable_models())

                # If the page doesn't have a revision (eg, came from import-export), create one.
                if revision is None:
                    revision = page.save_revision(changed=False)

                for target_locale in form.cleaned_data['locales']:
                    # Work out target root. While we're at it, get list of any translatable
                    # ancestor pages that don't have translations yet as these will need to
                    # be translated too.
                    required_ancestors = []
                    current_page = page
                    target_root = current_page.get_translation_or_none(target_locale)
                    while target_root is None:
                        current_page = current_page.get_parent()

                        if issubclass(current_page.specific_class, translatable_models):
                            target_root = current_page.specific.get_translation_or_none(target_locale)

                            if target_root is None:
                                required_ancestors.append(current_page)
                        else:
                            target_root = current_page
                            break

                    # Create translation request
                    translation_request = TranslationRequest.objects.create(
                        source_locale=source_locale,
                        target_locale=target_locale,
                        target_root=target_root,
                        created_at=timezone.now(),
                        created_by=request.user,
                    )

                    # Add ancestor pages to translation request
                    parent_item = None
                    for ancestor_page in required_ancestors:
                        source_revision = ancestor_page.get_latest_revision()
                        if source_revision is None:
                            source_revision = ancestor_page.specific.save_revision(changed=False)

                        parent_item = TranslationRequestPage.objects.create(
                            request=translation_request,
                            source_revision=source_revision,
                            parent=parent_item,
                        )

                    # Now add the requested page
                    parent_item = TranslationRequestPage.objects.create(
                        request=translation_request,
                        source_revision=revision,
                        parent=parent_item,
                    )

                    # Now add the sub tree
                    if form.cleaned_data['include_subtree']:
                        def _walk(current_page, parent_item):
                            for child_page in current_page.get_children():
                                if not issubclass(child_page.specific_class, translatable_models):
                                    continue

                                source_revision = child_page.get_latest_revision()
                                if source_revision is None:
                                    source_revision = child_page.specific.save_revision(changed=False)

                                child_item = TranslationRequestPage.objects.create(
                                    request=translation_request,
                                    source_revision=source_revision,
                                    parent=parent_item,
                                )

                                if child_page.numchild:
                                    _walk(child_page, child_item)

                        _walk(page, parent_item)

                messages.success(request, "The translation request was submitted successfully")
                return redirect('wagtailadmin_explore', page.get_parent().id)
    else:
        form = CreateTranslationRequestForm(page)

    return render(request, 'wagtail_i18n_workflow/create_translation_request.html', {
        'page': page,
        'form': form,
    })
