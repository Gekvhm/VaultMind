import os
import re

class DocumentIngester:
    def __init__(self, chunk_size=1000, chunk_overlap=200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        # Регулярні вирази для Obsidian вікі-посилань, тегів та жирного тексту
        self.wiki_link_pattern = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')
        self.tag_pattern = re.compile(r'#([a-zA-Z0-9_\-/]+)')
        self.bold_pattern = re.compile(r'\*\*([^*]+)\*\*')

    def clean_frontmatter(self, text):
        """Видаляє YAML frontmatter з початку файлу, але повертає його метадані."""
        meta = {}
        if text.startswith('---'):
            parts = text.split('---', 2)
            if len(parts) >= 3:
                frontmatter_text = parts[1]
                content_text = parts[2]
                # Спрощений парсинг YAML ключ-значення
                for line in frontmatter_text.split('\n'):
                    if ':' in line:
                        key, val = line.split(':', 1)
                        meta[key.strip()] = val.strip().strip('"').strip("'")
                return content_text.strip(), meta
        return text, meta

    def extract_structural_entities(self, text, file_name):
        """Вилучає сутності та зв'язки на основі структури документа."""
        entities = []
        relations = []
        
        # Основна сутність - сам документ
        doc_entity = (file_name, "Document")
        entities.append(doc_entity)
        
        # Вилучення вікі-посилань
        links = self.wiki_link_pattern.findall(text)
        for link in links:
            target_name = link.strip()
            entities.append((target_name, "Document"))
            relations.append((file_name, "links_to", target_name))
            
        # Вилучення тегів
        tags = self.tag_pattern.findall(text)
        for tag in tags:
            tag_name = f"#{tag.strip()}"
            entities.append((tag_name, "Tag"))
            relations.append((file_name, "has_tag", tag_name))
            
        # Вилучення жирних концептів
        bolds = self.bold_pattern.findall(text)
        for bold in bolds:
            concept_name = bold.strip()
            # Обмежуємо довжину сутності, щоб уникнути спаму довгими реченнями
            if len(concept_name) < 50:
                entities.append((concept_name, "Concept"))
                relations.append((file_name, "mentions", concept_name))

        return list(set(entities)), list(set(relations))

    def chunk_text(self, text, file_path, base_entities, base_relations):
        """Розбиває текст на чанки з ковзним вікном та прив'язкою сутностей."""
        chunks = []
        text_len = len(text)
        start = 0
        
        # Спрощене вилучення поточного заголовка перед кожним чанком
        lines = text.split('\n')
        current_heading = "Root"
        
        # Допоміжний список заголовків з їх позиціями
        headings_with_pos = []
        pos = 0
        for line in lines:
            if line.startswith('#'):
                m = re.match(r'^(#+)\s+(.+)$', line)
                if m:
                    heading_text = m.group(2).strip()
                    headings_with_pos.append((pos, heading_text))
            pos += len(line) + 1

        while start < text_len:
            end = min(start + self.chunk_size, text_len)
            
            # Спроба вирівняти кінець чанку по реченню або абзацу
            if end < text_len:
                # Шукаємо останню крапку чи перенесення рядка у кінці вікна
                search_area = text[end - 150 : end]
                match = re.search(r'[\.\?\!\n]', search_area[::-1])
                if match:
                    end = end - match.start()
            
            chunk_content = text[start:end].strip()
            
            # Визначаємо поточний заголовок для чанку
            for pos, h_text in headings_with_pos:
                if pos <= start:
                    current_heading = h_text
                else:
                    break
            
            # Локальні сутності для конкретного чанку
            chunk_entities = []
            # Перевіряємо які базові сутності присутні у цьому чанку
            for ent_name, ent_type in base_entities:
                if ent_name in chunk_content and ent_name != os.path.basename(file_path):
                    chunk_entities.append((ent_name, ent_type))
            
            chunks.append({
                "file_path": file_path,
                "heading": current_heading,
                "content": chunk_content,
                "entities": list(set(chunk_entities))
            })
            
            start = end - self.chunk_overlap
            if start >= text_len - 50: # Занадто малий залишок
                break
                
        return chunks

    def process_file(self, file_path):
        """Зчитує та обробляє один файл, повертаючи чанки та графові зв'язки."""
        with open(file_path, 'r', encoding='utf-8') as f:
            raw_content = f.read()
            
        file_name = os.path.basename(file_path)
        content, meta = self.clean_frontmatter(raw_content)
        
        base_entities, base_relations = self.extract_structural_entities(content, file_name)
        
        # Додаємо метадані frontmatter до графа
        for key, val in meta.items():
            meta_entity = (val, "Metadata")
            base_entities.append(meta_entity)
            base_relations.append((file_name, f"meta_{key}", val))
            
        chunks = self.chunk_text(content, file_path, base_entities, base_relations)
        
        return {
            "chunks": chunks,
            "entities": base_entities,
            "relations": base_relations
        }

    def process_directory(self, dir_path):
        """Обробляє всі markdown та текстові файли в директорії."""
        all_chunks = []
        all_entities = []
        all_relations = []
        
        for root, _, files in os.walk(dir_path):
            for file in files:
                if file.endswith(('.md', '.txt')):
                    file_path = os.path.join(root, file)
                    try:
                        result = self.process_file(file_path)
                        all_chunks.extend(result["chunks"])
                        all_entities.extend(result["entities"])
                        all_relations.extend(result["relations"])
                    except Exception as e:
                        print(f"Помилка обробки файлу {file_path}: {str(e)}")
                        
        # Очищення від дублікатів сутностей та зв'язків
        unique_entities = list(set(all_entities))
        unique_relations = list(set(all_relations))
        
        return {
            "chunks": all_chunks,
            "entities": unique_entities,
            "relations": unique_relations
        }
